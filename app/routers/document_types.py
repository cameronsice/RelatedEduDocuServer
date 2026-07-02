"""Document type configuration endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import DocumentTypeIn
from app.services.document_types import document_type_service, CORE_FIELDS, FIELD_DATA_TYPES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/document-types", tags=["document-types"])


@router.get("")
def list_document_types(db: Session = Depends(get_db)):
    """
    List active document types and the fields each one uses.

    The frontend uses this to render type-aware forms: which fields to show
    for a given type, and which are required.
    """
    return {"document_types": document_type_service.list_types(db)}


@router.get("/manage")
def list_all_document_types(db: Session = Depends(get_db)):
    """All types (active + inactive) with full config — for the admin page."""
    return {"document_types": document_type_service.list_all(db)}


@router.get("/field-library")
def field_library():
    """The core fields available to add to any type, plus supported data types."""
    return {
        "core_fields": [
            {"key": key, "label": meta["label"], "data_type": meta["data_type"]}
            for key, meta in CORE_FIELDS.items()
        ],
        "data_types": list(FIELD_DATA_TYPES),
    }


@router.get("/{key}/usage")
def document_type_usage(key: str, db: Session = Depends(get_db)):
    """How many documents use this type (used for the delete warning)."""
    return {"key": key, "count": document_type_service.usage_count(db, key)}


@router.post("")
def create_document_type(payload: DocumentTypeIn, db: Session = Depends(get_db)):
    """Create a new document type."""
    try:
        dt = document_type_service.create_type(db, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return document_type_service.get_type(db, dt.key)


@router.put("/{key}")
def update_document_type(key: str, payload: DocumentTypeIn, db: Session = Depends(get_db)):
    """Update an existing document type (label, fields, order, active)."""
    try:
        document_type_service.update_type(db, key, payload.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return document_type_service.get_type(db, key)


@router.delete("/{key}")
def delete_document_type(key: str, db: Session = Depends(get_db)):
    """
    Hard-delete a document type. The UI should call `/usage` first and warn the
    user when documents still use this type (those documents are left intact but
    will reference a type that no longer exists).
    """
    try:
        document_type_service.delete_type(db, key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"message": f"Document type '{key}' deleted"}
