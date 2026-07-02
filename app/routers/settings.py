"""Application settings endpoints (AI extraction config)."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AISettingsIn
from app.services.settings import (
    settings_service,
    AI_ENABLED, AI_PROVIDER, AI_MODEL, AI_API_KEY, AI_BASE_URL,
)
from app.services.ai_extractor import ai_extractor_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/ai")
def get_ai_settings(db: Session = Depends(get_db)):
    """Current AI extraction settings (API key never returned, only whether set)."""
    return settings_service.ai_config_public(db)


@router.put("/ai")
def update_ai_settings(payload: AISettingsIn, db: Session = Depends(get_db)):
    """Update AI extraction settings. Blank api_key keeps the existing key."""
    values = {}
    if payload.enabled is not None:
        values[AI_ENABLED] = "true" if payload.enabled else "false"
    if payload.provider is not None:
        values[AI_PROVIDER] = payload.provider.strip()
    if payload.model is not None:
        values[AI_MODEL] = payload.model.strip()
    if payload.base_url is not None:
        values[AI_BASE_URL] = payload.base_url.strip()
    # Only overwrite the key when a non-empty value is provided.
    if payload.api_key:
        values[AI_API_KEY] = payload.api_key.strip()

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
    config = {
        "provider": payload.provider or saved["provider"],
        "model": (payload.model or "").strip() or saved["model"],
        "base_url": (payload.base_url or "").strip() or None,
        "api_key": (payload.api_key or "").strip() or saved["api_key"],
    }
    return ai_extractor_service.test_connection(config)
