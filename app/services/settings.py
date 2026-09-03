"""Application settings service (DB-backed key/value).

Used for runtime-configurable settings — the AI provider, model, API key,
base URL, and the cost guards (daily call limit, OCR-text cap) — so they can be
changed from the Settings page without editing .env. Values fall back to
environment variables when unset.

Also keeps a per-day AI usage counter (calls + tokens) in the same table, which
the daily call limit is enforced against.
"""

import json
import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AppSetting
from app.config import OPENAI_API_KEY
from app.services.llm import DEFAULT_PROVIDER, provider_preset

logger = logging.getLogger(__name__)

# Setting keys
AI_ENABLED = "ai_enabled"
AI_PROVIDER = "ai_provider"
AI_MODEL = "ai_model"
AI_API_KEY = "ai_api_key"
AI_BASE_URL = "ai_base_url"
# Cost guards
AI_DAILY_CALL_LIMIT = "ai_daily_call_limit"   # 0 = unlimited
AI_TEXT_MAX_CHARS = "ai_text_max_chars"       # OCR chars sent per AI call
AI_MAX_IMAGES = "ai_max_images"               # hard cap on page images per call
AI_CLASSIFY_ENABLED = "ai_classify_enabled"   # AI type identification fallback

# Sensible defaults (used when no DB value and no env fallback)
DEFAULTS = {
    AI_ENABLED: "true",
    AI_PROVIDER: DEFAULT_PROVIDER,
    AI_MODEL: "gpt-4o-mini",
    AI_BASE_URL: "",
    AI_DAILY_CALL_LIMIT: "2000",
    AI_TEXT_MAX_CHARS: "6000",
    AI_MAX_IMAGES: "5",
    AI_CLASSIFY_ENABLED: "true",
}

USAGE_PREFIX = "ai_usage:"  # + YYYY-MM-DD


def _to_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class SettingsService:
    """Read/write DB-backed application settings."""

    def get(self, db: Session, key: str, default: Optional[str] = None) -> Optional[str]:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row is not None and row.value is not None:
            return row.value
        if default is not None:
            return default
        return DEFAULTS.get(key)

    def set(self, db: Session, key: str, value: Optional[str]) -> None:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if not row:
            row = AppSetting(key=key)
            db.add(row)
        row.value = value

    def set_many(self, db: Session, values: dict) -> None:
        for key, value in values.items():
            self.set(db, key, value)
        db.commit()

    def ai_config(self, db: Session) -> dict:
        """Resolved AI config, with env fallback for the API key."""
        api_key = self.get(db, AI_API_KEY) or OPENAI_API_KEY or ""
        base_url = (self.get(db, AI_BASE_URL) or "").strip()
        enabled = str(self.get(db, AI_ENABLED, "true")).lower() == "true"
        provider = (self.get(db, AI_PROVIDER) or DEFAULT_PROVIDER).strip().lower()
        return {
            "enabled": enabled,
            "provider": provider,
            "model": (self.get(db, AI_MODEL) or "").strip() or provider_preset(provider)["model"],
            "api_key": api_key,
            "base_url": base_url or None,
            "daily_call_limit": max(0, _to_int(self.get(db, AI_DAILY_CALL_LIMIT), 2000)),
            "text_max_chars": max(500, _to_int(self.get(db, AI_TEXT_MAX_CHARS), 6000)),
            "max_images": max(1, _to_int(self.get(db, AI_MAX_IMAGES), 5)),
            "classify_enabled": str(self.get(db, AI_CLASSIFY_ENABLED, "true")).lower() == "true",
        }

    def ai_config_public(self, db: Session) -> dict:
        """AI config for display — never returns the raw API key."""
        cfg = self.ai_config(db)
        return {
            "enabled": cfg["enabled"],
            "provider": cfg["provider"],
            "model": cfg["model"],
            "base_url": cfg["base_url"] or "",
            "api_key_set": bool(cfg["api_key"]),
            "daily_call_limit": cfg["daily_call_limit"],
            "text_max_chars": cfg["text_max_chars"],
            "max_images": cfg["max_images"],
            "classify_enabled": cfg["classify_enabled"],
            "usage_today": self.usage_for(db, date.today()),
        }

    # --- AI usage metering ---------------------------------------------

    def usage_for(self, db: Session, day: date) -> dict:
        raw = self.get(db, f"{USAGE_PREFIX}{day.isoformat()}", "")
        data = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        if raw:
            try:
                data.update({k: int(v) for k, v in json.loads(raw).items() if k in data})
            except (ValueError, TypeError, AttributeError):
                pass
        data["date"] = day.isoformat()
        return data

    def record_usage(self, db: Session, calls: int, input_tokens: int, output_tokens: int) -> dict:
        """Add to today's counter. Commits immediately so the guard is durable."""
        today = date.today()
        data = self.usage_for(db, today)
        data["calls"] += int(calls or 0)
        data["input_tokens"] += int(input_tokens or 0)
        data["output_tokens"] += int(output_tokens or 0)
        self.set(
            db,
            f"{USAGE_PREFIX}{today.isoformat()}",
            json.dumps({k: data[k] for k in ("calls", "input_tokens", "output_tokens")}),
        )
        db.commit()
        return data

    def calls_remaining_today(self, db: Session, limit: int) -> Optional[int]:
        """None = unlimited; otherwise how many AI calls are still allowed today."""
        if not limit or limit <= 0:
            return None
        return max(0, limit - self.usage_for(db, date.today())["calls"])

    def usage_history(self, db: Session, days: int = 30) -> list[dict]:
        rows = (
            db.query(AppSetting)
            .filter(AppSetting.key.like(f"{USAGE_PREFIX}%"))
            .order_by(AppSetting.key.desc())
            .limit(days)
            .all()
        )
        out = []
        for row in rows:
            try:
                d = json.loads(row.value or "{}")
            except ValueError:
                d = {}
            out.append(
                {
                    "date": row.key[len(USAGE_PREFIX):],
                    "calls": int(d.get("calls", 0) or 0),
                    "input_tokens": int(d.get("input_tokens", 0) or 0),
                    "output_tokens": int(d.get("output_tokens", 0) or 0),
                }
            )
        return out


# Global instance
settings_service = SettingsService()
