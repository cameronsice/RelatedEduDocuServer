"""SQLAlchemy database models."""

import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, Text, Date, DateTime, Boolean, Float
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Document(Base):
    """Model for storing scanned educational documents."""
    
    __tablename__ = "documents"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_name = Column(String(255), nullable=True, index=True)
    student_name = Column(String(255), nullable=True, index=True)
    assignment_name = Column(String(255), nullable=True, index=True)
    grade = Column(String(50), nullable=True)
    document_date = Column(Date, nullable=True)
    original_filename = Column(String(500), nullable=False)
    stored_path = Column(String(1000), nullable=False)
    ocr_text = Column(Text, nullable=True)
    extraction_confidence = Column(Float, nullable=True)
    requires_review = Column(Boolean, nullable=False, default=False)
    review_reason = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Document(id={self.id}, student={self.student_name}, course={self.course_name})>"

