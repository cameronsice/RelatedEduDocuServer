"""Document CRUD API endpoints."""

import logging
import re
import tempfile
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document
from app.schemas import DocumentResponse, DocumentUpdate, DocumentListResponse
from app.services.storage import storage_service
from app.services.ocr_service import ocr_service
from app.services.ai_extractor import ai_extractor_service
from app.config import SCAN_REVIEW_HOLD_PATH

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

ALLOWED_DOCUMENT_TYPES = ("poe", "certificate")


def _normalize_document_type(value: Optional[str]) -> str:
    """Return 'poe' or 'certificate'; default to 'poe' if invalid."""
    if not value:
        return "poe"
    v = value.strip().lower()
    return v if v in ALLOWED_DOCUMENT_TYPES else "poe"


def _detect_document_type_from_ocr(ocr_text: Optional[str]) -> str:
    """If 'Certificate issued' appears in OCR text (case-insensitive), return 'certificate'; else 'poe'."""
    if not ocr_text:
        return "poe"
    return "certificate" if "certificate issued" in ocr_text.lower() else "poe"


def _extract_student_id_fallback(ocr_text: Optional[str]) -> Optional[str]:
    """Extract first 13-digit number from text as fallback for student ID."""
    if not ocr_text:
        return None
    match = re.search(r"\b\d{13}\b", ocr_text)
    return match.group(0) if match else None


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

    # Only check confidence if there are missing fields
    # If all fields are manually filled, we trust the user's input regardless of confidence
    if missing and (
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


def find_and_delete_original_file(original_filename: str) -> bool:
    """
    Find and delete the original file from the _review_queue folder.
    
    Handles cases where the file might have a counter suffix (e.g., file_1.pdf).
    
    Args:
        original_filename: The original filename to search for
        
    Returns:
        True if file was found and deleted, False otherwise
    """
    if not original_filename:
        return False
    
    review_queue_path = SCAN_REVIEW_HOLD_PATH.resolve()
    if not review_queue_path.exists():
        return False
    
    # Try exact match first
    exact_match = review_queue_path / original_filename
    if exact_match.exists():
        try:
            exact_match.unlink()
            logger.info(f"Deleted original file from review queue: {exact_match}")
            return True
        except Exception as e:
            logger.warning(f"Failed to delete original file {exact_match}: {e}")
            return False
    
    # Try with counter suffix pattern (e.g., filename_1.pdf, filename_2.pdf)
    file_stem = Path(original_filename).stem
    file_suffix = Path(original_filename).suffix
    
    # Search for files matching the pattern (exact name or with counter suffix)
    # Check files with counter suffix up to a reasonable limit
    for counter in range(1, 101):  # Check up to filename_100.pdf
        counter_match = review_queue_path / f"{file_stem}_{counter}{file_suffix}"
        if counter_match.exists():
            try:
                counter_match.unlink()
                logger.info(f"Deleted original file from review queue: {counter_match}")
                return True
            except Exception as e:
                logger.warning(f"Failed to delete original file {counter_match}: {e}")
                return False
    
    logger.debug(f"Original file not found in review queue: {original_filename}")
    return False


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
    document_type: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Upload and process a new document. Optional document_type: 'poe' or 'certificate'."""
    suffix = Path(file.filename).suffix or ".dat"
    
    # Use a temporary file outside of the watched scan folder
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(temp_file.name)
    
    try:
        contents = await file.read()
        temp_file.write(contents)
        temp_file.close()
        
        document_type_override = _normalize_document_type(document_type) if document_type else None
        
        document = process_document(
            temp_path,
            db,
            original_filename=file.filename,
            document_type_override=document_type_override,
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
        if key == "document_type":
            value = _normalize_document_type(value)
        if key == "student_id" and value == "":
            value = None
        if value is not None:
            setattr(document, key, value)
        elif key in ("student_id", "course_name", "student_name", "assignment_name", "grade", "document_date", "document_type"):
            setattr(document, key, value)
    
    # Default date to today if missing after update
    if document.document_date is None:
        document.document_date = date.today()
    
    refresh_review_status(document)

    if document.requires_review and not previous_review_state:
        document.stored_path = storage_service.move_to_review_storage(document.stored_path)
    elif previous_review_state and not document.requires_review:
        # Moving from review to final storage - clean up original file from _review_queue
        document.stored_path = storage_service.move_to_final_storage(document.stored_path)
        find_and_delete_original_file(document.original_filename)

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
    
    # Also try to delete the original file from _review_queue folder (if it exists)
    # This handles cases where the document was in review queue
    find_and_delete_original_file(document.original_filename)
    
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
    original_filename: Optional[str] = None,
    document_type_override: Optional[str] = None,
) -> Document:
    """
    Process a document: OCR, extract fields, store, rename to descriptive name, and save to database.
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
    
    # 4. Document type: override from upload or detect from OCR
    document_type = (
        _normalize_document_type(document_type_override)
        if document_type_override
        else _detect_document_type_from_ocr(ocr_text)
    )
    
    # 5. Student ID: from AI or regex fallback (13-digit number)
    extracted_student_id = extracted.student_id if extracted.student_id and extracted.student_id.strip() else None
    if not extracted_student_id:
        extracted_student_id = _extract_student_id_fallback(ocr_text)
    
    # 6. Parse date if available, default to today if missing
    document_date = None
    if extracted.document_date:
        validated_date = ai_extractor_service.validate_date(extracted.document_date)
        if validated_date:
            document_date = date.fromisoformat(validated_date)
    if document_date is None:
        document_date = date.today()

    requires_review, review_reason = determine_review_status(
        course_name=extracted.course_name,
        student_name=extracted.student_name,
        assignment_name=extracted.assignment_name,
        grade=extracted.grade,
        document_date=document_date,
        extraction_confidence=extraction_confidence,
    )
    
    # 7. Move to review or final storage
    if requires_review:
        stored_path = storage_service.move_to_review_storage(str(stored_path))
    else:
        stored_path = storage_service.move_to_final_storage(str(stored_path))
    
    # 8. Rename stored file to descriptive name (Student_Course_Type_Last4.ext)
    stored_path = storage_service.rename_to_descriptive(
        str(stored_path),
        student_name=extracted.student_name,
        course_name=extracted.course_name,
        document_type=document_type,
        student_id=extracted_student_id,
    )
    
    document = Document(
        id=document_uuid,
        course_name=extracted.course_name,
        student_name=extracted.student_name,
        assignment_name=extracted.assignment_name,
        grade=extracted.grade,
        document_date=document_date,
        document_type=document_type,
        student_id=extracted_student_id,
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

