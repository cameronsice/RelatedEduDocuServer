"""Document CRUD API endpoints."""

import logging
import tempfile
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document
from app.schemas import DocumentResponse, DocumentUpdate, DocumentListResponse
from app.services.storage import storage_service
from app.services.ocr_service import ocr_service
from app.services.ai_extractor import ai_extractor_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

REQUIRED_FIELDS: List[str] = [
    "course_name",
    "student_name",
    "assignment_name",
    "grade",
    "document_date",
]
CONFIDENCE_THRESHOLD = 0.6


def determine_review_status(
    *,
    course_name: Optional[str],
    student_name: Optional[str],
    assignment_name: Optional[str],
    grade: Optional[str],
    document_date: Optional[date],
    extraction_confidence: Optional[float],
) -> tuple[bool, Optional[str]]:
    """Return whether the document needs review and why."""
    reasons: List[str] = []
    field_values = {
        "course_name": course_name,
        "student_name": student_name,
        "assignment_name": assignment_name,
        "grade": grade,
        "document_date": document_date,
    }

    missing = [
        label.replace("_", " ").title()
        for label, value in field_values.items()
        if not value
    ]
    if missing:
        reasons.append(f"Missing: {', '.join(missing)}")

    if (
        extraction_confidence is not None
        and extraction_confidence < CONFIDENCE_THRESHOLD
    ):
        reasons.append(
            f"Low confidence ({extraction_confidence:.2f} < {CONFIDENCE_THRESHOLD:.2f})"
        )

    if reasons:
        return True, "; ".join(reasons)
    return False, None


def refresh_review_status(document: Document) -> None:
    """Recalculate the review flags for a document."""
    needs_review, reason = determine_review_status(
        course_name=document.course_name,
        student_name=document.student_name,
        assignment_name=document.assignment_name,
        grade=document.grade,
        document_date=document.document_date,
        extraction_confidence=document.extraction_confidence,
    )
    document.requires_review = needs_review
    document.review_reason = reason


@router.get("", response_model=DocumentListResponse)
def list_documents(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db)
):
    """List all documents with pagination."""
    offset = (page - 1) * page_size
    
    total = db.query(Document).count()
    documents = (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(doc) for doc in documents],
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/review-queue", response_model=DocumentListResponse)
def list_review_queue(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db)
):
    """List documents that require manual review."""
    offset = (page - 1) * page_size

    base_query = db.query(Document).filter(Document.requires_review.is_(True))
    total = base_query.count()
    documents = (
        base_query
        .order_by(Document.updated_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(doc) for doc in documents],
        total=total,
        page=page,
        page_size=page_size
    )


@router.post("/upload/manual", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload and process a new document."""
    suffix = Path(file.filename).suffix or ".dat"
    
    # Use a temporary file outside of the watched scan folder
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(temp_file.name)
    
    try:
        contents = await file.read()
        temp_file.write(contents)
        temp_file.close()
        
        # Process the document with the original filename preserved
        document = process_document(
            temp_path,
            db,
            original_filename=file.filename
        )
        
        return DocumentResponse.model_validate(document)
        
    finally:
        # Clean up temp file
        if temp_path.exists():
            temp_path.unlink()


@router.get("/{document_id:uuid}", response_model=DocumentResponse)
def get_document(document_id: UUID, db: Session = Depends(get_db)):
    """Get a specific document by ID."""
    document = db.query(Document).filter(Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return DocumentResponse.model_validate(document)


@router.post("/{document_id:uuid}", response_model=DocumentResponse)
def update_document(
    document_id: UUID,
    update_data: DocumentUpdate,
    db: Session = Depends(get_db)
):
    """Update document fields (for manual correction)."""
    document = db.query(Document).filter(Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    previous_review_state = document.requires_review

    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        if value is not None:
            setattr(document, key, value)
    
    refresh_review_status(document)

    if document.requires_review and not previous_review_state:
        document.stored_path = storage_service.move_to_review_storage(document.stored_path)
    elif previous_review_state and not document.requires_review:
        document.stored_path = storage_service.move_to_final_storage(document.stored_path)

    document.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(document)
    
    return DocumentResponse.model_validate(document)


@router.delete("/{document_id:uuid}")
def delete_document(document_id: UUID, db: Session = Depends(get_db)):
    """Delete a document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Delete the stored file
    storage_service.delete_document(document.stored_path)
    
    # Delete from database
    db.delete(document)
    db.commit()
    
    return {"message": "Document deleted successfully"}


@router.get("/{document_id:uuid}/file")
def get_document_file(document_id: UUID, db: Session = Depends(get_db)):
    """Download the original document file."""
    document = db.query(Document).filter(Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    file_path = storage_service.get_document_path(document.stored_path)
    
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=file_path,
        filename=document.original_filename,
        media_type="application/octet-stream"
    )


@router.get("/{document_id:uuid}/preview/{page_num}")
def get_document_preview(
    document_id: UUID,
    page_num: int = 1,
    db: Session = Depends(get_db)
):
    """Get a preview image for a document page."""
    document = db.query(Document).filter(Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    stored_path = Path(document.stored_path)
    
    # If it's an image, return the main file
    if stored_path.suffix.lower() in {'.jpg', '.jpeg', '.png'}:
        file_path = storage_service.get_document_path(document.stored_path)
        if file_path and file_path.exists():
            return FileResponse(path=file_path, media_type="image/jpeg")
    
    # If it's a PDF, get the preview image
    preview_paths = storage_service.get_preview_paths(document.stored_path)
    
    if not preview_paths:
        raise HTTPException(status_code=404, detail="No preview available")
    
    if page_num < 1 or page_num > len(preview_paths):
        raise HTTPException(status_code=404, detail="Page not found")
    
    return FileResponse(path=preview_paths[page_num - 1], media_type="image/jpeg")


def process_document(
    file_path: Path,
    db: Session,
    original_filename: Optional[str] = None
) -> Document:
    """
    Process a document: OCR, extract fields, store, and save to database.
    
    Args:
        file_path: Path to the document file
        db: Database session
        
    Returns:
        Created Document model
    """
    logger.info(f"Processing document: {file_path}")
    
    # 1. Store and optimize the document
    doc_id, stored_path = storage_service.store_document(file_path)
    try:
        document_uuid = UUID(str(doc_id))
    except (ValueError, TypeError):
        document_uuid = uuid4()
    
    # 2. Perform OCR
    ocr_text = ocr_service.extract_text(file_path)
    
    # 3. Extract fields using AI
    extracted = ai_extractor_service.extract_fields(ocr_text or "")
    extraction_confidence = extracted.confidence or 0.0
    
    # 4. Parse date if available
    document_date = None
    if extracted.document_date:
        validated_date = ai_extractor_service.validate_date(extracted.document_date)
        if validated_date:
            document_date = date.fromisoformat(validated_date)

    requires_review, review_reason = determine_review_status(
        course_name=extracted.course_name,
        student_name=extracted.student_name,
        assignment_name=extracted.assignment_name,
        grade=extracted.grade,
        document_date=document_date,
        extraction_confidence=extraction_confidence,
    )
    
    # 5. Create database record
    if requires_review:
        stored_path = storage_service.move_to_review_storage(str(stored_path))
    else:
        stored_path = storage_service.move_to_final_storage(str(stored_path))
    
    document = Document(
        id=document_uuid,
        course_name=extracted.course_name,
        student_name=extracted.student_name,
        assignment_name=extracted.assignment_name,
        grade=extracted.grade,
        document_date=document_date,
        original_filename=original_filename or file_path.name,
        stored_path=str(stored_path),
        ocr_text=ocr_text,
        extraction_confidence=extraction_confidence,
        requires_review=requires_review,
        review_reason=review_reason,
    )
    
    db.add(document)
    db.commit()
    db.refresh(document)
    
    logger.info(f"Document processed and saved: {document.id}")
    return document

