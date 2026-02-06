"""Search API endpoints."""

import logging
from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.database import get_db
from app.models import Document
from app.schemas import DocumentResponse, DocumentListResponse, SearchQuery

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=DocumentListResponse)
def search_documents(
    query: Optional[str] = Query(None, description="General search query"),
    student_name: Optional[str] = Query(None, description="Filter by student name"),
    course_name: Optional[str] = Query(None, description="Filter by course name"),
    assignment_name: Optional[str] = Query(None, description="Filter by assignment name"),
    student_id: Optional[str] = Query(None, description="Filter by student ID"),
    date_from: Optional[date] = Query(None, description="Filter from date"),
    date_to: Optional[date] = Query(None, description="Filter to date"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    """
    Search documents with various filters.
    
    The general query searches across student name, course name, 
    assignment name, and OCR text.
    """
    base_query = db.query(Document)
    filters = []
    
    # General search query - searches across multiple fields
    if query:
        search_pattern = f"%{query}%"
        filters.append(
            or_(
                Document.student_name.ilike(search_pattern),
                Document.course_name.ilike(search_pattern),
                Document.assignment_name.ilike(search_pattern),
                Document.student_id.ilike(search_pattern),
                Document.ocr_text.ilike(search_pattern)
            )
        )
    
    # Specific field filters
    if student_name:
        filters.append(Document.student_name.ilike(f"%{student_name}%"))
    
    if course_name:
        filters.append(Document.course_name.ilike(f"%{course_name}%"))
    
    if assignment_name:
        filters.append(Document.assignment_name.ilike(f"%{assignment_name}%"))
    
    if student_id:
        filters.append(Document.student_id.ilike(f"%{student_id}%"))
    
    # Date range filters
    if date_from:
        filters.append(Document.document_date >= date_from)
    
    if date_to:
        filters.append(Document.document_date <= date_to)
    
    # Apply all filters
    if filters:
        base_query = base_query.filter(and_(*filters))
    
    # Get total count
    total = base_query.count()
    
    # Apply pagination
    offset = (page - 1) * page_size
    documents = (
        base_query
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


@router.get("/students")
def list_students(
    query: Optional[str] = Query(None, description="Filter students by name"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    db: Session = Depends(get_db)
):
    """Get a list of unique student names."""
    base_query = db.query(Document.student_name).distinct()
    
    if query:
        base_query = base_query.filter(
            Document.student_name.ilike(f"%{query}%")
        )
    
    results = (
        base_query
        .filter(Document.student_name.isnot(None))
        .limit(limit)
        .all()
    )
    
    return {"students": [r[0] for r in results if r[0]]}


@router.get("/courses")
def list_courses(
    query: Optional[str] = Query(None, description="Filter courses by name"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    db: Session = Depends(get_db)
):
    """Get a list of unique course names."""
    base_query = db.query(Document.course_name).distinct()
    
    if query:
        base_query = base_query.filter(
            Document.course_name.ilike(f"%{query}%")
        )
    
    results = (
        base_query
        .filter(Document.course_name.isnot(None))
        .limit(limit)
        .all()
    )
    
    return {"courses": [r[0] for r in results if r[0]]}


@router.get("/assignments")
def list_assignments(
    query: Optional[str] = Query(None, description="Filter assignments by name"),
    course_name: Optional[str] = Query(None, description="Filter by course"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    db: Session = Depends(get_db)
):
    """Get a list of unique assignment names."""
    base_query = db.query(Document.assignment_name).distinct()
    
    if query:
        base_query = base_query.filter(
            Document.assignment_name.ilike(f"%{query}%")
        )
    
    if course_name:
        base_query = base_query.filter(
            Document.course_name.ilike(f"%{course_name}%")
        )
    
    results = (
        base_query
        .filter(Document.assignment_name.isnot(None))
        .limit(limit)
        .all()
    )
    
    return {"assignments": [r[0] for r in results if r[0]]}

