"""Application settings service (DB-backed key/value).

Used for runtime-configurable settings — currently the AI extraction provider,
model, API key and base URL — so they can be changed from the Settings page
without editing .env. Values fall back to environment variables when unset.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AppSetting
from app.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

# Setting keys
AI_ENABLED = "ai_enabled"
AI_PROVIDER = "ai_provider"
AI_MODEL = "ai_model"
AI_API_KEY = "ai_api_key"
AI_BASE_URL = "ai_base_url"

# Sensible defaults (used when no DB value and no env fallback)
DEFAULTS = {
    AI_ENABLED: "true",
    AI_PROVIDER: "openai",
    AI_MODEL: "gpt-4o-mini",
    AI_BASE_URL: "",
}


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
        return {
            "enabled": enabled,
            "provider": self.get(db, AI_PROVIDER, "openai"),
            "model": self.get(db, AI_MODEL, "gpt-4o-mini"),
            "api_key": api_key,
            "base_url": base_url or None,
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
        }


# Global instance
settings_service = SettingsService()
