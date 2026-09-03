"""Document CRUD API endpoints."""

import logging
import re
import tempfile
from datetime import datetime, date
from pathlib import Path
import json
import queue
import threading
from typing import Optional, List, Callable
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import Document
from app.schemas import DocumentResponse, DocumentUpdate, DocumentListResponse
from app.services.storage import storage_service
from app.services.ocr_service import ocr_service
from app.services.ai_extractor import ai_extractor_service
from app.services.document_types import document_type_service
from app.services import field_values
from app.services.settings import settings_service
from app.services.rules_extractor import rules_extractor, validate_sa_id
from app.config import SCAN_REVIEW_HOLD_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

CONFIDENCE_THRESHOLD = 0.6


def _normalize_document_type(db: Session, value: Optional[str]) -> str:
    """Return a valid, configured document type key; default if invalid."""
    return document_type_service.normalize_type(db, value)


def _identify_document_type(
    db: Session,
    ocr_text: Optional[str],
    filename: Optional[str],
    ai_config: dict,
) -> tuple[str, dict]:
    """
    Identify the document type. Deterministic first (filename patterns and
    detection keywords configured per type), then - only if nothing matched and
    AI classification is enabled - one cheap text-only model call. Falls back
    to the default type. Returns (type_key, ai_usage).
    """
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "error": None}
    detected = document_type_service.detect_type(db, ocr_text, filename)
    if detected:
        logger.info("Type identified by rules: %s (%s)", detected, filename)
        return _normalize_document_type(db, detected), usage

    if ai_config.get("enabled") and ai_config.get("api_key") and ai_config.get("classify_enabled"):
        result = ai_extractor_service.classify(
            db, ocr_text, filename, document_type_service.list_types(db), ai_config
        )
        usage.update({k: result.get(k, 0) for k in ("calls", "input_tokens", "output_tokens")})
        usage["error"] = result.get("error")
        if result.get("type"):
            logger.info(
                "Type identified by AI: %s (confidence %.2f, %s)",
                result["type"], result.get("confidence", 0.0), filename,
            )
            return _normalize_document_type(db, result["type"]), usage

    logger.info("Type not identified for %s; using default", filename)
    return _normalize_document_type(db, None), usage


def _extract_student_id_fallback(ocr_text: Optional[str]) -> Optional[str]:
    """Extract first 13-digit number from text as fallback for student ID."""
    if not ocr_text:
        return None
    match = re.search(r"\b\d{13}\b", ocr_text)
    return match.group(0) if match else None


def determine_review_status(
    db: Session,
    document_type: Optional[str],
    field_values: dict,
    extraction_confidence: Optional[float],
) -> tuple[bool, Optional[str]]:
    """
    Return whether the document needs review and why.

    Only the fields configured as *required* for this document's type are
    checked, so e.g. a Certificate is not flagged for a missing Grade.
    """
    reasons: List[str] = []

    required = document_type_service.required_fields(db, document_type)
    missing = [
        field["label"]
        for field in required
        if not field_values.get(field["key"])
    ]
    if missing:
        reasons.append(f"Missing: {', '.join(missing)}")

    # Only check confidence if there are missing fields.
    # If all required fields are filled, we trust the user's input regardless.
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


def refresh_review_status(db: Session, document: Document) -> None:
    """Recalculate the review flags for a document."""
    values = {
        "course_name": document.course_name,
        "student_name": document.student_name,
        "assignment_name": document.assignment_name,
        "grade": document.grade,
        "document_date": document.document_date,
        "student_id": document.student_id,
    }
    # Include custom field values so required custom fields are considered.
    values.update(field_values.get_values(db, document.id))

    needs_review, reason = determine_review_status(
        db,
        document.document_type,
        values,
        document.extraction_confidence,
    )
    document.requires_review = needs_review
    document.review_reason = reason


def build_document_response(db: Session, document: Document) -> DocumentResponse:
    """Build a document response including its custom field values."""
    response = DocumentResponse.model_validate(document)
    response.custom_fields = field_values.get_values(db, document.id)
    return response


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
        
        document_type_override = _normalize_document_type(db, document_type) if document_type else None
        
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


@router.post("/bulk-upload")
async def bulk_upload_document(file: UploadFile = File(...)):
    """
    Process one document with live per-stage progress, streamed as NDJSON.

    Clients upload files ONE AT A TIME (keeping processing serial so the server
    isn't overwhelmed). Each call streams stage events:
    ``{"stage": "identify"|"ocr"|"ai"}`` and finally either
    ``{"stage": "done", "result": "approved"|"review", "document_id": ...}`` or
    ``{"stage": "error", "message": ...}``.
    """
    suffix = Path(file.filename).suffix or ".dat"
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(temp_file.name)
    contents = await file.read()
    temp_file.write(contents)
    temp_file.close()
    original_filename = file.filename

    def event_stream():
        events: queue.Queue = queue.Queue()
        final: dict = {}

        def worker():
            db = SessionLocal()
            try:
                document = process_document(
                    temp_path,
                    db,
                    original_filename=original_filename,
                    progress_callback=lambda stage: events.put({"stage": stage}),
                )
                final["event"] = {
                    "stage": "done",
                    "result": "review" if document.requires_review else "approved",
                    "document_id": str(document.id),
                    "document_type": document.document_type,
                    "student_name": document.student_name,
                    "ai_used": document.ai_used,
                    "extraction_error": document.extraction_error,
                }
            except Exception as exc:
                logger.error(f"Bulk processing failed for {original_filename}: {exc}")
                final["event"] = {"stage": "error", "message": str(exc)}
            finally:
                db.close()
                if temp_path.exists():
                    temp_path.unlink()
                events.put(None)  # sentinel

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        while True:
            item = events.get()
            if item is None:
                break
            yield json.dumps(item) + "\n"
        yield json.dumps(final.get("event", {"stage": "error", "message": "unknown error"})) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.get("/{document_id:uuid}", response_model=DocumentResponse)
def get_document(document_id: UUID, db: Session = Depends(get_db)):
    """Get a specific document by ID."""
    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    return build_document_response(db, document)


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
    custom_input = update_dict.pop("custom_fields", None)
    for key, value in update_dict.items():
        if key == "document_type":
            value = _normalize_document_type(db, value)
        if key == "student_id" and value == "":
            value = None
        if value is not None:
            setattr(document, key, value)
        elif key in ("student_id", "course_name", "student_name", "assignment_name", "grade", "document_date", "document_type"):
            setattr(document, key, value)

    # Persist custom (type-specific) field values into the values table.
    if custom_input:
        custom_map = document_type_service.custom_field_map(db, document.document_type)
        for field_key, raw_value in custom_input.items():
            field = custom_map.get(field_key)
            if not field:
                continue  # ignore fields that don't belong to this type
            field_values.set_value(db, document.id, field_key, field["data_type"], raw_value)
        db.flush()  # make new values visible to the review-status query below

    # Default date to today if missing after update
    if document.document_date is None:
        document.document_date = date.today()

    refresh_review_status(db, document)

    if document.requires_review and not previous_review_state:
        document.stored_path = storage_service.move_to_review_storage(document.stored_path)
    elif previous_review_state and not document.requires_review:
        # Moving from review to final storage - clean up original file from _review_queue
        document.stored_path = storage_service.move_to_final_storage(document.stored_path)
        find_and_delete_original_file(document.original_filename)

    document.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(document)

    return build_document_response(db, document)


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

    # Remove any custom field values for this document
    field_values.delete_values(db, document.id)

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


CORE_FIELD_KEYS = ("course_name", "student_name", "assignment_name", "grade", "student_id")


def _parse_document_date(value) -> date:
    """Parse a YYYY-MM-DD (or common) date string; default to today."""
    if value:
        validated = ai_extractor_service.validate_date(str(value))
        if not validated:
            try:
                validated = date.fromisoformat(str(value)).isoformat()
            except ValueError:
                validated = None
        if validated:
            try:
                return date.fromisoformat(validated)
            except ValueError:
                pass
    return date.today()


def process_document(
    file_path: Path,
    db: Session,
    original_filename: Optional[str] = None,
    document_type_override: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Document:
    """
    Process a document through the extraction cascade:

        OCR (first N pages) -> rules-based extraction
          -> if any required field missing, vision AI on the first N page images
          -> merge (validated rules win, AI fills gaps)
          -> if still incomplete or uncertain, route to the review queue.

    N is the document type's ``max_pages`` (caps both OCR and what AI sees).
    """
    logger.info(f"Processing document: {file_path}")

    def _notify(stage: str) -> None:
        if progress_callback:
            try:
                progress_callback(stage)
            except Exception:
                pass

    # 1. Store and optimize the document
    doc_id, stored_path = storage_service.store_document(file_path)
    try:
        document_uuid = UUID(str(doc_id))
    except (ValueError, TypeError):
        document_uuid = uuid4()

    # 2. Resolve document type (needed to know the page cap and field set).
    _notify("identify")
    ai_config = settings_service.ai_config(db)
    ai_input_tokens = 0
    ai_output_tokens = 0
    ai_calls = 0
    source_name = original_filename or file_path.name
    if document_type_override:
        document_type = _normalize_document_type(db, document_type_override)
        detect_text = None
    else:
        # Cheap single-page OCR just to identify the type.
        detect_text = ocr_service.extract_text(file_path, max_pages=1)
        document_type, identify_usage = _identify_document_type(db, detect_text, source_name, ai_config)
        ai_calls += identify_usage["calls"]
        ai_input_tokens += identify_usage["input_tokens"]
        ai_output_tokens += identify_usage["output_tokens"]

    type_config = document_type_service.get_type(db, document_type) or {}
    max_pages = int(type_config.get("max_pages", 1) or 1)

    # 3. OCR up to the type's page cap (reuse the detection pass when possible).
    _notify("ocr")
    if detect_text is not None and max_pages <= 1:
        ocr_text = detect_text
    else:
        ocr_text = ocr_service.extract_text(file_path, max_pages=max_pages)

    # 4. Tier 1 — deterministic rules extraction.
    values = dict(rules_extractor.extract(ocr_text, type_config))

    required_keys = document_type_service.required_field_keys(db, document_type)
    missing_required = [k for k in required_keys if not values.get(k)]

    # 5. Tier 2 — AI fallback (text first, images only if needed), only if
    #    rules left required fields empty. Budget-guarded: when the daily AI
    #    call limit is reached the document goes to review instead.
    used_ai = ai_calls > 0
    ai_error = None
    ai_skipped = None
    confidence = 0.9  # deterministic rules are treated as high-confidence
    if missing_required and ai_config.get("enabled") and ai_config.get("api_key"):
        _notify("ai")
        ai_result = ai_extractor_service.extract(
            db, file_path, type_config, ai_config, ocr_text, required_keys, known_values=values
        )
        ai_calls += ai_result["calls"]
        ai_input_tokens += ai_result["input_tokens"]
        ai_output_tokens += ai_result["output_tokens"]
        if ai_result.get("budget_exhausted"):
            ai_skipped = ai_result.get("error") or "AI daily call limit reached"
        else:
            used_ai = True
            ai_error = ai_result.get("error")
            confidence = float(ai_result.get("confidence") or 0.0)
        for key, val in ai_result.get("values", {}).items():
            values.setdefault(key, val)  # rules-validated values win; AI fills gaps

    # 6. Validate the ID by checksum — never trust an unvalidated ID.
    if values.get("student_id") and not validate_sa_id(values["student_id"]):
        values.pop("student_id", None)

    # 7. Date: parse and default to today.
    document_date = _parse_document_date(values.get("document_date"))
    values["document_date"] = document_date.isoformat()

    # 8. Review gate: missing required fields, or AI was uncertain.
    requires_review, review_reason = determine_review_status(
        db, document_type, values, confidence
    )
    if used_ai and not requires_review and confidence < CONFIDENCE_THRESHOLD:
        requires_review = True
        review_reason = f"Low AI confidence ({confidence:.2f} < {CONFIDENCE_THRESHOLD:.2f})"
    # An AI failure always needs a human look, and must be visible as such.
    if ai_error:
        requires_review = True
        review_reason = f"AI extraction failed; {review_reason}" if review_reason else "AI extraction failed"
    # Budget guard tripped: no money spent, but the fields still need a human.
    if ai_skipped:
        requires_review = True
        review_reason = f"AI skipped ({ai_skipped}); {review_reason}" if review_reason else f"AI skipped ({ai_skipped})"

    # 9. Move to review or final storage.
    if requires_review:
        stored_path = storage_service.move_to_review_storage(str(stored_path))
    else:
        stored_path = storage_service.move_to_final_storage(str(stored_path))

    # 10. Rename stored file to a descriptive name.
    stored_path = storage_service.rename_to_descriptive(
        str(stored_path),
        student_name=values.get("student_name"),
        course_name=values.get("course_name"),
        document_type=document_type,
        student_id=values.get("student_id"),
    )

    document = Document(
        id=document_uuid,
        course_name=values.get("course_name"),
        student_name=values.get("student_name"),
        assignment_name=values.get("assignment_name"),
        grade=values.get("grade"),
        document_date=document_date,
        document_type=document_type,
        student_id=values.get("student_id"),
        original_filename=original_filename or file_path.name,
        stored_path=str(stored_path),
        ocr_text=ocr_text,
        extraction_confidence=confidence,
        ai_used=used_ai,
        extraction_error=ai_error,
        ai_input_tokens=ai_input_tokens or None,
        ai_output_tokens=ai_output_tokens or None,
        requires_review=requires_review,
        review_reason=review_reason,
    )
    db.add(document)
    db.flush()  # assign the row so custom field values can reference it

    # 11. Persist any custom (type-specific) field values into the typed store.
    custom_fields = {
        f["key"]: f for f in type_config.get("fields", []) if f.get("source") == "custom"
    }
    for key, field in custom_fields.items():
        if values.get(key):
            field_values.set_value(db, document_uuid, key, field["data_type"], values[key])

    db.commit()
    db.refresh(document)

    logger.info(
        "Document processed: %s (type=%s, ai=%s, ai_calls=%d, tokens=%d/%d, review=%s)",
        document.id, document_type, used_ai, ai_calls, ai_input_tokens, ai_output_tokens, requires_review,
    )
    return document

