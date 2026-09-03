"""Pydantic schemas for request/response validation."""

from datetime import date, datetime
from typing import Optional, Any
from uuid import UUID
from pydantic import BaseModel, Field


class DocumentBase(BaseModel):
    """Base schema for document fields."""
    course_name: Optional[str] = None
    student_name: Optional[str] = None
    assignment_name: Optional[str] = None
    grade: Optional[str] = None
    document_date: Optional[date] = None
    document_type: Optional[str] = None
    student_id: Optional[str] = None


class DocumentCreate(DocumentBase):
    """Schema for creating a document."""
    original_filename: str
    stored_path: str
    ocr_text: Optional[str] = None
    extraction_confidence: Optional[float] = None
    requires_review: bool = False
    review_reason: Optional[str] = None


class DocumentUpdate(DocumentBase):
    """Schema for updating a document."""
    requires_review: Optional[bool] = None
    review_reason: Optional[str] = None
    # Values for custom (type-specific) fields, keyed by field_key.
    custom_fields: Optional[dict[str, Any]] = None


class DocumentResponse(DocumentBase):
    """Schema for document response."""
    id: UUID
    original_filename: str
    stored_path: str
    ocr_text: Optional[str] = None
    extraction_confidence: Optional[float] = None
    ai_used: bool = False
    extraction_error: Optional[str] = None
    ai_input_tokens: Optional[int] = None
    ai_output_tokens: Optional[int] = None
    requires_review: bool
    review_reason: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Schema for paginated document list."""
    documents: list[DocumentResponse]
    total: int
    page: int
    page_size: int


class SearchQuery(BaseModel):
    """Schema for search query parameters."""
    query: Optional[str] = None
    student_name: Optional[str] = None
    course_name: Optional[str] = None
    assignment_name: Optional[str] = None
    student_id: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class FieldConfigIn(BaseModel):
    """A field within a document type (create/update)."""
    key: str
    label: Optional[str] = None
    data_type: Optional[str] = None  # used for custom fields
    required: bool = False
    visible: bool = True
    description: Optional[str] = None      # hint for the AI prompt
    aliases: Optional[list[str]] = None    # extra labels for rules extraction
    handwritten: bool = False              # skip text rules; AI reads the image


class DocumentTypeIn(BaseModel):
    """Schema for creating/updating a document type."""
    key: Optional[str] = None  # required on create; ignored on update
    label: str
    sort_order: int = 0
    is_active: bool = True
    max_pages: Optional[int] = None  # pages to OCR / send to AI
    detect_keywords: Optional[list[str]] = None    # OCR substrings that identify the type
    filename_patterns: Optional[list[str]] = None  # filename substrings that identify the type
    ai_input: Optional[str] = None  # text_then_images | text | images
    fields: list[FieldConfigIn] = Field(default_factory=list)


class AISettingsIn(BaseModel):
    """Schema for updating AI extraction settings."""
    enabled: Optional[bool] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    # Only applied when non-empty; blank means "keep existing key".
    api_key: Optional[str] = None
    # Cost guards
    daily_call_limit: Optional[int] = None
    text_max_chars: Optional[int] = None
    max_images: Optional[int] = None
    classify_enabled: Optional[bool] = None
