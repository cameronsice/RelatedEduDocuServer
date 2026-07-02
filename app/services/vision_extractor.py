"""Vision-AI field extraction (the cascade's fallback tier).

When rules-based extraction can't fill every required field, this renders the
first N page images (N = the document type's max_pages) and asks the configured
multimodal model for *only that type's* fields. Reading the image directly is
what makes handwriting (e.g. POE learner details) tractable.

Uses an OpenAI-compatible client, so the same code talks to OpenAI, Azure
OpenAI, or a local/self-hosted endpoint via the configured base URL.
"""

import base64
import json
import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

from openai import OpenAI
from PIL import Image
from pdf2image import convert_from_path

from app.config import POPPLER_PATH
from app.services.llm import safe_chat_completion

logger = logging.getLogger(__name__)

_MAX_DIM = 1600  # cap image size sent to the model


def _render_page_images(file_path: Path, max_pages: int) -> list[str]:
    """Render the first `max_pages` pages to JPEG base64 data URLs."""
    max_pages = max(1, int(max_pages or 1))
    suffix = file_path.suffix.lower()
    images: list[Image.Image] = []

    if suffix == ".pdf":
        images = convert_from_path(file_path, dpi=150, first_page=1, last_page=max_pages, poppler_path=POPPLER_PATH)
    else:
        images = [Image.open(file_path)]

    urls: list[str] = []
    for img in images[:max_pages]:
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > _MAX_DIM:
            scale = _MAX_DIM / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, "JPEG", quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        urls.append(f"data:image/jpeg;base64,{b64}")
    return urls


def _build_prompt(type_config: dict) -> str:
    fields = type_config.get("fields", [])
    field_lines = "\n".join(
        f"- {f['key']}: {f['label']} ({f['data_type']})" for f in fields
    )
    shape = ", ".join(f'"{f["key"]}": "value or null"' for f in fields)
    label = type_config.get("label", "document")
    return (
        f"You are extracting information from a scanned {label} (page images attached).\n"
        f"Extract these fields:\n{field_lines}\n\n"
        "Rules: dates as YYYY-MM-DD; a 13-digit ID as digits only; read handwriting "
        "carefully; if a field is not present, use null.\n"
        f'Respond ONLY with a JSON object: {{{shape}, "confidence": 0.0}} '
        "where confidence (0.0-1.0) is your overall certainty."
    )


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


class VisionExtractor:
    """Type-aware multimodal extraction over the first N page images."""

    def extract(
        self,
        file_path: Path,
        type_config: dict,
        config: dict,
        max_pages: int,
    ) -> dict:
        """
        Returns {"values": {field_key: value}, "confidence": float}.
        Returns empty values if AI is disabled, unconfigured, or on any error.
        """
        if not config or not config.get("enabled") or not config.get("api_key"):
            logger.info("Vision AI skipped: disabled or no API key")
            return {"values": {}, "confidence": 0.0, "error": None}

        try:
            images = _render_page_images(file_path, max_pages)
            if not images:
                return {"values": {}, "confidence": 0.0, "error": "Could not render page images"}

            client = OpenAI(api_key=config["api_key"], base_url=config.get("base_url") or None)
            content = [{"type": "text", "text": _build_prompt(type_config)}]
            for url in images:
                content.append({"type": "image_url", "image_url": {"url": url}})

            messages = [
                {
                    "role": "system",
                    "content": "You extract fields from document images and respond only with valid JSON.",
                },
                {"role": "user", "content": content},
            ]
            response = safe_chat_completion(
                client, config.get("model") or "gpt-4o-mini", messages, 700
            )
            raw = (response.choices[0].message.content or "").strip()
            data = _parse_json(raw)
            if not data:
                return {"values": {}, "confidence": 0.0, "error": "AI returned unparseable output"}

            confidence = float(data.pop("confidence", 0.0) or 0.0)
            valid_keys = {f["key"] for f in type_config.get("fields", [])}
            values = {
                k: str(v).strip()
                for k, v in data.items()
                if k in valid_keys and v not in (None, "", "null")
            }
            return {"values": values, "confidence": confidence, "error": None}

        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            logger.error(f"Vision extraction failed for {file_path}: {message}")
            return {"values": {}, "confidence": 0.0, "error": message[:480]}


# Global instance
vision_extractor = VisionExtractor()
