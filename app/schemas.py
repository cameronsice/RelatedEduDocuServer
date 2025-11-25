"""Pydantic schemas for request/response validation."""

from datetime import date, datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


class DocumentBase(BaseModel):
    """Base schema for document fields."""
    course_name: Optional[str] = None
    student_name: Optional[str] = None
    assignment_name: Optional[str] = None
    grade: Optional[str] = None
    document_date: Optional[date] = None


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


class DocumentResponse(DocumentBase):
    """Schema for document response."""
    id: UUID
    original_filename: str
    stored_path: str
    ocr_text: Optional[str] = None
    extraction_confidence: Optional[float] = None
    requires_review: bool
    review_reason: Optional[str] = None
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
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ExtractedFields(BaseModel):
    """Schema for AI-extracted fields from OCR text."""
    course_name: Optional[str] = None
    student_name: Optional[str] = None
    assignment_name: Optional[str] = None
    grade: Optional[str] = None
    document_date: Optional[str] = None
    confidence: float = 0.0

