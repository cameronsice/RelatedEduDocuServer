"""SQLAlchemy database models."""

import uuid
from datetime import datetime, date
from sqlalchemy import (
    Column, String, Text, Date, DateTime, Boolean, Float, Uuid, Integer, JSON,
    ForeignKey, UniqueConstraint,
)

from app.database import Base


class Document(Base):
    """Model for storing scanned educational documents."""
    
    __tablename__ = "documents"
    
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_name = Column(String(255), nullable=True, index=True)
    student_name = Column(String(255), nullable=True, index=True)
    assignment_name = Column(String(255), nullable=True, index=True)
    grade = Column(String(50), nullable=True)
    document_date = Column(Date, nullable=True)
    document_type = Column(String(50), nullable=True, default="poe")
    student_id = Column(String(20), nullable=True, index=True)
    original_filename = Column(String(500), nullable=False)
    stored_path = Column(String(1000), nullable=False)
    ocr_text = Column(Text, nullable=True)
    extraction_confidence = Column(Float, nullable=True)
    # Whether the AI (vision) tier ran for this document, and the error message
    # if that AI call failed (so failures are visible, not silently swallowed).
    ai_used = Column(Boolean, nullable=False, default=False)
    extraction_error = Column(String(500), nullable=True)
    requires_review = Column(Boolean, nullable=False, default=False)
    review_reason = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Document(id={self.id}, student={self.student_name}, course={self.course_name})>"


class DocumentType(Base):
    """
    A configurable document type (e.g. POE, Certificate) and the set of
    fields it uses. This makes types and their fields data rather than code.

    `fields` is an ordered list of field configs, each shaped like:
        {"key": "grade", "required": false, "visible": true, "sort_order": 5}
    Field labels / input types are resolved from the field registry in
    app.services.document_types (CORE_FIELDS) when serving to clients.
    """

    __tablename__ = "document_types"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), unique=True, nullable=False, index=True)
    label = Column(String(120), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    fields = Column(JSON, nullable=False, default=list)
    # Max pages to OCR / send to AI for this type (caps cost and data sent).
    max_pages = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<DocumentType(key={self.key}, label={self.label})>"


class AppSetting(Base):
    """Simple key/value application settings (e.g. AI provider config).

    Stored in the DB so they can be changed at runtime from the Settings page
    instead of editing .env and restarting.
    """

    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<AppSetting(key={self.key})>"


class DocumentFieldValue(Base):
    """
    Value of a *custom* field for a document.

    Core fields (student_name, course_name, grade, document_date, student_id,
    assignment_name) live in columns on the Document model. Custom fields
    defined per document type are stored here, one row per (document, field),
    with the value written to the typed column matching the field's data_type.
    `value_text` is always populated (string form) so text search works
    uniformly across every field; `value_number` / `value_date` are populated
    additionally for number / date fields to allow range and exact queries.

    This keeps the `documents` table unchanged while making every field
    uniformly searchable and giving the MCP a predictable, typed query surface.
    """

    __tablename__ = "document_field_values"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id"),
        nullable=False,
        index=True,
    )
    field_key = Column(String(100), nullable=False, index=True)
    value_text = Column(String(500), nullable=True, index=True)
    value_number = Column(Float, nullable=True, index=True)
    value_date = Column(Date, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("document_id", "field_key", name="uq_docfieldvalue_doc_key"),
    )

    def __repr__(self):
        return f"<DocumentFieldValue(document_id={self.document_id}, field_key={self.field_key})>"

