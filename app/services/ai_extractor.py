"""AI field extraction and type classification (the cascade's paid tier).

One prompt builder, driven entirely by the document type's field config, feeds
two input tiers:

* **text tier** - the OCR text only (capped at ``text_max_chars``). Cheap:
  roughly a thousand input tokens per call. Good enough for printed, templated
  documents where Tesseract already read the words correctly.
* **image tier** - the first N page images *plus* the OCR text. Expensive
  (each page image costs on the order of a thousand input tokens or more), so
  it is the last resort: handwriting, stamps, ID cards, poor scans.

Which tiers run is decided per document type (``ai_input``):

    text_then_images  text first; images only if required fields are still
                      missing or the model was unsure (default)
    text              text only, never images (cheapest; typed forms)
    images            straight to images (handwritten POEs, ID cards)

Cost guards, all configurable on the Settings page:

* AI runs only when the free rules tier left a *required* field empty
  (decided by the caller, see ``process_document``).
* ``daily_call_limit`` - a hard cap on AI calls per day. When reached, AI is
  skipped and the document goes to the review queue instead of costing money.
* ``text_max_chars`` and ``max_images`` cap what a single call can contain.
* Every call's token usage is metered per document and per day.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image
from pdf2image import convert_from_path
from sqlalchemy.orm import Session

from app.config import POPPLER_PATH
from app.services.llm import LLMImage, LLMResult, get_provider
from app.services.settings import settings_service

logger = logging.getLogger(__name__)

# Below this the text tier is assumed to be unsure and images are tried
# (when the type allows it).
CONFIDENCE_THRESHOLD = 0.6

# Text with fewer alphanumeric characters than this is treated as "no usable
# OCR" and the text tier is skipped straight to images (when allowed).
MIN_USABLE_TEXT_CHARS = 40

_MAX_IMAGE_DIM = 1600  # cap image size sent to the model (pixels, long side)

SYSTEM_PROMPT = (
    "You extract fields from scanned educational and workplace documents "
    "and respond only with valid JSON."
)


class BudgetExceeded(RuntimeError):
    """Raised when the daily AI call limit has been reached."""


# --- Helpers -------------------------------------------------------------


def _parse_json(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
    except json.JSONDecodeError:
        pass
    return None


def _usable_text(ocr_text: Optional[str]) -> bool:
    if not ocr_text:
        return False
    return sum(1 for ch in ocr_text if ch.isalnum()) >= MIN_USABLE_TEXT_CHARS


def _render_page_images(file_path: Path, max_pages: int) -> list[LLMImage]:
    """Render the first `max_pages` pages to JPEG bytes."""
    max_pages = max(1, int(max_pages or 1))
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        images = convert_from_path(
            file_path, dpi=150, first_page=1, last_page=max_pages, poppler_path=POPPLER_PATH
        )
    else:
        images = [Image.open(file_path)]

    out: list[LLMImage] = []
    for img in images[:max_pages]:
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > _MAX_IMAGE_DIM:
            scale = _MAX_IMAGE_DIM / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, "JPEG", quality=80)
        out.append(LLMImage(data=buf.getvalue(), media_type="image/jpeg"))
    return out


def build_extraction_prompt(type_config: dict, ocr_text: Optional[str], with_images: bool) -> str:
    """The single prompt builder: fields (with hints) from the type config."""
    fields = type_config.get("fields", [])
    lines = []
    for f in fields:
        hint = f.get("description") or ""
        aliases = [a for a in (f.get("aliases") or []) if a]
        extra = []
        if hint:
            extra.append(hint)
        if aliases:
            extra.append("often labelled: " + ", ".join(f'"{a}"' for a in aliases[:6]))
        if f.get("handwritten"):
            extra.append("usually handwritten" + (" - read it from the image" if with_images else ""))
        detail = f" - {'; '.join(extra)}" if extra else ""
        lines.append(f"- {f['key']}: {f['label']} ({f['data_type']}){detail}")
    field_lines = "\n".join(lines)
    shape = ", ".join(f'"{f["key"]}": "value or null"' for f in fields)
    label = type_config.get("label", "document")

    source = []
    if with_images:
        source.append("the attached page images")
    if ocr_text:
        source.append("the OCR text below")
    source_desc = " and ".join(source) or "the document"

    prompt = (
        f"You are extracting information from a scanned {label}. Use {source_desc}.\n"
        f"Extract these fields (key: label (type) - hints):\n{field_lines}\n\n"
        "Rules: dates as YYYY-MM-DD; a 13-digit ID as digits only; keep names and "
        "titles exactly as written; "
        + ("read handwriting carefully; " if with_images else "")
        + "if a field is not present, use null. Never invent a value.\n"
        f'Respond ONLY with a JSON object: {{{shape}, "confidence": 0.0}} '
        "where confidence (0.0-1.0) is your overall certainty."
    )
    if ocr_text and with_images:
        prompt += (
            "\n\nOCR text (machine-read, may contain recognition errors - where it "
            "disagrees with the image, trust the image, especially for digits):\n"
            f"\"\"\"\n{ocr_text}\n\"\"\""
        )
    elif ocr_text:
        prompt += f"\n\nOCR text:\n\"\"\"\n{ocr_text}\n\"\"\""
    return prompt


def build_classification_prompt(types: list[dict], ocr_text: str, filename: Optional[str]) -> str:
    lines = []
    for t in types:
        hints = []
        if t.get("detect_keywords"):
            hints.append("keywords: " + ", ".join(t["detect_keywords"][:5]))
        field_names = ", ".join(f["label"] for f in t.get("fields", [])[:6])
        if field_names:
            hints.append("fields: " + field_names)
        lines.append(f"- {t['key']}: {t['label']}" + (f" ({'; '.join(hints)})" if hints else ""))
    keys = ", ".join(f'"{t["key"]}"' for t in types)
    type_lines = "\n".join(lines)
    prompt = (
        "Classify this scanned document as one of these document types:\n"
        f"{type_lines}\n\n"
        f"Allowed keys: {keys}.\n"
        f"Original filename: {filename or 'unknown'}\n"
        'Respond ONLY with JSON: {"type": "<key or null>", "confidence": 0.0}\n\n'
        f"OCR text of the first page:\n\"\"\"\n{ocr_text}\n\"\"\""
    )
    return prompt


# --- Service -------------------------------------------------------------


class AIExtractorService:
    """Type-aware extraction with text-first / image-fallback tiers and cost guards."""

    def _call(
        self,
        db: Optional[Session],
        cfg: dict,
        prompt: str,
        images: Optional[list[LLMImage]],
        max_output_tokens: int,
        purpose: str,
    ) -> LLMResult:
        """One metered, budget-guarded provider call."""
        if db is not None:
            remaining = settings_service.calls_remaining_today(db, cfg.get("daily_call_limit", 0))
            if remaining is not None and remaining <= 0:
                raise BudgetExceeded(
                    f"AI daily call limit ({cfg.get('daily_call_limit')}) reached"
                )
        provider = get_provider(cfg)
        start = time.perf_counter()
        result = provider.complete(SYSTEM_PROMPT, prompt, images=images, max_output_tokens=max_output_tokens)
        elapsed = int((time.perf_counter() - start) * 1000)
        logger.info(
            "AI %s via %s/%s: %d images, %d in / %d out tokens, %d ms",
            purpose, provider.kind, provider.model, len(images or []),
            result.input_tokens, result.output_tokens, elapsed,
        )
        if db is not None:
            settings_service.record_usage(db, 1, result.input_tokens, result.output_tokens)
        return result

    # -- extraction --------------------------------------------------------

    def extract(
        self,
        db: Optional[Session],
        file_path: Path,
        type_config: dict,
        cfg: dict,
        ocr_text: Optional[str],
        required_keys: list[str],
        known_values: Optional[dict] = None,
    ) -> dict:
        """
        Run the AI tier(s) for one document.

        Returns::

            {
              "values": {field_key: value},   # only keys defined on the type
              "confidence": float,
              "error": str | None,            # provider error message
              "budget_exhausted": bool,       # daily limit hit, nothing called
              "calls": int, "input_tokens": int, "output_tokens": int,
              "tiers": ["text", "images"],   # which tiers actually ran
            }
        """
        out = {
            "values": {}, "confidence": 0.0, "error": None, "budget_exhausted": False,
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "tiers": [],
        }
        if not cfg or not cfg.get("enabled") or not cfg.get("api_key"):
            logger.info("AI skipped: disabled or no API key")
            return out

        mode = (type_config.get("ai_input") or "text_then_images").lower()
        text_cap = int(cfg.get("text_max_chars") or 6000)
        text = (ocr_text or "")[:text_cap].strip() or None
        valid_keys = {f["key"] for f in type_config.get("fields", [])}
        max_tokens = 200 + 60 * max(1, len(valid_keys))
        known = dict(known_values or {})

        def _still_missing(values: dict) -> list[str]:
            merged = dict(known)
            merged.update(values)
            return [k for k in required_keys if not merged.get(k)]

        handwritten = {f["key"] for f in type_config.get("fields", []) if f.get("handwritten")}

        try:
            # Tier A: text only. Skipped when a missing required field is
            # marked handwritten - OCR text will not have it, so the text call
            # would be wasted.
            needs_image = bool(handwritten & set(_still_missing({})))
            run_text = (
                mode in ("text", "text_then_images") and _usable_text(text)
                and not (mode == "text_then_images" and needs_image)
            )
            if run_text:
                result = self._call(
                    db, cfg, build_extraction_prompt(type_config, text, with_images=False),
                    None, max_tokens, "extract(text)",
                )
                self._absorb(out, result, "text")
                values, confidence = self._parse_values(result.text, valid_keys)
                logger.info("AI text tier values: %s (confidence %.2f)", values, confidence)
                out["values"].update(values)
                out["confidence"] = confidence
                if mode == "text":
                    return out
                if not _still_missing(out["values"]) and confidence >= CONFIDENCE_THRESHOLD:
                    return out
                logger.info(
                    "Text tier insufficient (missing=%s, confidence=%.2f); escalating to images",
                    _still_missing(out["values"]), confidence,
                )
            elif mode == "text":
                out["error"] = "No usable OCR text and this type is text-only"
                return out

            # Tier B: images (+ text).
            max_pages = min(
                int(type_config.get("max_pages", 1) or 1), int(cfg.get("max_images") or 5)
            )
            images = _render_page_images(file_path, max_pages)
            if not images:
                out["error"] = "Could not render page images"
                return out
            image_text = text if (mode == "text_then_images" and _usable_text(text)) else None
            result = self._call(
                db, cfg, build_extraction_prompt(type_config, image_text, with_images=True),
                images, max_tokens, "extract(images)",
            )
            self._absorb(out, result, "images")
            values, confidence = self._parse_values(result.text, valid_keys)
            logger.info("AI image tier values: %s (confidence %.2f)", values, confidence)
            if not values and confidence == 0.0 and not _parse_json(result.text):
                out["error"] = "AI returned unparseable output"
                return out
            out["values"].update(values)  # image reading overrides the text guess
            out["confidence"] = confidence
            return out

        except BudgetExceeded as exc:
            out["budget_exhausted"] = True
            out["error"] = str(exc)
            logger.warning("%s - skipping AI for %s", exc, file_path)
            return out
        except Exception as exc:  # noqa: BLE001 - surfaced on the document
            message = f"{type(exc).__name__}: {exc}"
            logger.error(f"AI extraction failed for {file_path}: {message}")
            out["error"] = message[:480]
            return out

    @staticmethod
    def _absorb(out: dict, result: LLMResult, tier: str) -> None:
        out["calls"] += 1
        out["input_tokens"] += result.input_tokens
        out["output_tokens"] += result.output_tokens
        out["tiers"].append(tier)

    @staticmethod
    def _parse_values(text: str, valid_keys: set) -> tuple[dict, float]:
        data = _parse_json(text or "")
        if not data:
            return {}, 0.0
        try:
            confidence = float(data.pop("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        values = {
            k: str(v).strip()
            for k, v in data.items()
            if k in valid_keys and v not in (None, "", "null")
        }
        return values, max(0.0, min(1.0, confidence))

    # -- classification ----------------------------------------------------

    def classify(
        self,
        db: Optional[Session],
        ocr_text: Optional[str],
        filename: Optional[str],
        types: list[dict],
        cfg: dict,
    ) -> dict:
        """
        Ask the model which configured type a document is. Text only, first
        ~1500 characters - a very cheap call. Returns
        {"type": key|None, "confidence": float, "error": str|None, tokens...}.
        """
        out = {"type": None, "confidence": 0.0, "error": None, "calls": 0, "input_tokens": 0, "output_tokens": 0}
        if not cfg or not cfg.get("enabled") or not cfg.get("api_key") or not cfg.get("classify_enabled", True):
            return out
        if not types or not _usable_text(ocr_text):
            return out
        snippet = (ocr_text or "")[:1500]
        try:
            result = self._call(
                db, cfg, build_classification_prompt(types, snippet, filename), None, 80, "classify"
            )
            out["calls"] = 1
            out["input_tokens"] = result.input_tokens
            out["output_tokens"] = result.output_tokens
            data = _parse_json(result.text) or {}
            key = str(data.get("type") or "").strip().lower()
            try:
                confidence = float(data.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            allowed = {t["key"] for t in types}
            if key in allowed and confidence >= 0.5:
                out["type"] = key
            out["confidence"] = confidence
        except BudgetExceeded as exc:
            out["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {exc}"[:480]
            logger.error("AI classification failed: %s", out["error"])
        return out

    # -- diagnostics -------------------------------------------------------

    def test_connection(self, config: dict) -> dict:
        """
        Make a minimal round-trip to verify the provider/model/key/base_url.
        Not metered against the daily limit. Returns {ok, message, model, response, latency_ms}.
        """
        config = config or {}
        if not config.get("api_key"):
            return {"ok": False, "message": "No API key configured.", "model": config.get("model")}
        try:
            provider = get_provider(config)
            start = time.perf_counter()
            result = provider.complete(
                "You are a connectivity check.", "Reply with the single word: OK", None, 100
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            return {
                "ok": True,
                "message": "Connection successful",
                "model": result.model or provider.model,
                "provider": provider.kind,
                "response": result.text,
                "latency_ms": latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"{type(exc).__name__}: {exc}", "model": config.get("model")}

    def validate_date(self, date_str: Optional[str]) -> Optional[str]:
        """Validate and normalize a date string to YYYY-MM-DD, or None."""
        if not date_str:
            return None
        formats = [
            "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None


# Global AI extractor service instance
ai_extractor_service = AIExtractorService()
