"""Application settings endpoints (AI extraction config + usage)."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AISettingsIn
from app.services.llm import PROVIDER_PRESETS, provider_preset
from app.services.settings import (
    settings_service,
    AI_ENABLED, AI_PROVIDER, AI_MODEL, AI_API_KEY, AI_BASE_URL,
    AI_DAILY_CALL_LIMIT, AI_TEXT_MAX_CHARS, AI_MAX_IMAGES, AI_CLASSIFY_ENABLED,
)
from app.services.ai_extractor import ai_extractor_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/ai")
def get_ai_settings(db: Session = Depends(get_db)):
    """Current AI extraction settings (API key never returned, only whether set)."""
    return settings_service.ai_config_public(db)


@router.get("/ai/providers")
def list_ai_providers():
    """Provider presets (label, default base URL and model) for the Settings page."""
    return {
        "providers": [
            {"key": key, "label": p["label"], "kind": p["kind"], "base_url": p["base_url"] or "", "model": p["model"]}
            for key, p in PROVIDER_PRESETS.items()
        ]
    }


@router.get("/ai/usage")
def get_ai_usage(days: int = 30, db: Session = Depends(get_db)):
    """Per-day AI call and token counts (newest first)."""
    cfg = settings_service.ai_config(db)
    return {
        "daily_call_limit": cfg["daily_call_limit"],
        "history": settings_service.usage_history(db, max(1, min(days, 365))),
    }


@router.put("/ai")
def update_ai_settings(payload: AISettingsIn, db: Session = Depends(get_db)):
    """Update AI extraction settings. Blank api_key keeps the existing key."""
    values = {}
    if payload.enabled is not None:
        values[AI_ENABLED] = "true" if payload.enabled else "false"
    if payload.provider is not None:
        values[AI_PROVIDER] = payload.provider.strip().lower()
    if payload.model is not None:
        values[AI_MODEL] = payload.model.strip()
    if payload.base_url is not None:
        values[AI_BASE_URL] = payload.base_url.strip()
    # Only overwrite the key when a non-empty value is provided.
    if payload.api_key:
        values[AI_API_KEY] = payload.api_key.strip()
    if payload.daily_call_limit is not None:
        values[AI_DAILY_CALL_LIMIT] = str(max(0, int(payload.daily_call_limit)))
    if payload.text_max_chars is not None:
        values[AI_TEXT_MAX_CHARS] = str(max(500, int(payload.text_max_chars)))
    if payload.max_images is not None:
        values[AI_MAX_IMAGES] = str(max(1, int(payload.max_images)))
    if payload.classify_enabled is not None:
        values[AI_CLASSIFY_ENABLED] = "true" if payload.classify_enabled else "false"

    if values:
        settings_service.set_many(db, values)
    return settings_service.ai_config_public(db)


@router.post("/ai/test")
def test_ai_connection(payload: AISettingsIn, db: Session = Depends(get_db)):
    """
    Test connectivity to the model using the submitted form values, falling
    back to the saved API key when the key field is left blank.
    """
    saved = settings_service.ai_config(db)
    provider = (payload.provider or saved["provider"]).strip().lower()
    # A blank model means the saved one - but only if the provider is the same;
    # otherwise the preset's default (an OpenAI model name is meaningless to xAI).
    model = (payload.model or "").strip()
    if not model:
        model = saved["model"] if provider == saved["provider"] else provider_preset(provider)["model"]
    config = {
        "provider": provider,
        "model": model,
        "base_url": (payload.base_url or "").strip() or None,
        "api_key": (payload.api_key or "").strip() or saved["api_key"],
    }
    return ai_extractor_service.test_connection(config)
