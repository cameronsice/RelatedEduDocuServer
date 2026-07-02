"""Read/write typed values for custom document fields.

Custom field values live in the document_field_values table (one row per
document+field). Each value is written to the typed column matching its
field's data_type, and `value_text` is always set (string form) so text search
works uniformly across every field.
"""

import logging
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import DocumentFieldValue

logger = logging.getLogger(__name__)


def _coerce(data_type: str, raw) -> tuple[Optional[str], Optional[float], Optional[date]]:
    """
    Split a raw input into (value_text, value_number, value_date) based on the
    field's data type. value_text is always the string form (for uniform text
    search); the typed column is set additionally for number/date fields.
    Returns all-None for empty input (meaning: no value / delete).
    """
    if raw is None:
        return None, None, None
    s = str(raw).strip()
    if not s:
        return None, None, None

    if data_type == "number":
        try:
            return s, float(s), None
        except ValueError:
            return s, None, None  # keep text form even if not parseable
    if data_type == "date":
        try:
            return s, None, date.fromisoformat(s)
        except ValueError:
            return s, None, None
    # text / id
    return s, None, None


def get_values(db: Session, document_id: UUID) -> dict:
    """Return {field_key: value_text} for a document's custom fields."""
    rows = (
        db.query(DocumentFieldValue)
        .filter(DocumentFieldValue.document_id == document_id)
        .all()
    )
    return {r.field_key: r.value_text for r in rows if r.value_text is not None}


def set_value(db: Session, document_id: UUID, field_key: str, data_type: str, raw) -> None:
    """Upsert a single custom field value (or delete it if empty)."""
    value_text, value_number, value_date = _coerce(data_type, raw)
    row = (
        db.query(DocumentFieldValue)
        .filter(
            DocumentFieldValue.document_id == document_id,
            DocumentFieldValue.field_key == field_key,
        )
        .first()
    )
    if value_text is None and value_number is None and value_date is None:
        if row:
            db.delete(row)
        return
    if not row:
        row = DocumentFieldValue(document_id=document_id, field_key=field_key)
        db.add(row)
    row.value_text = value_text
    row.value_number = value_number
    row.value_date = value_date


def delete_values(db: Session, document_id: UUID) -> None:
    """Remove all custom field values for a document (on document delete)."""
    db.query(DocumentFieldValue).filter(
        DocumentFieldValue.document_id == document_id
    ).delete()
