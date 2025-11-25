"""Main FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from app.config import (
    DEBUG,
    SCAN_FOLDER_PATH,
    STORAGE_PATH,
    SCAN_PROCESSED_PATH,
    SCAN_REVIEW_HOLD_PATH,
)
from app.database import init_db, get_db, SessionLocal
from app.routers import documents, search
from app.services.file_watcher import file_watcher_service
from app.routers.documents import process_document

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Get the app directory for templates and static files
APP_DIR = Path(__file__).parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR.parent / "static"

# Ensure directories exist
TEMPLATES_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)


def document_processor(file_path: Path):
    """Process a document when detected by file watcher."""
    db = SessionLocal()
    try:
        document = process_document(file_path, db)
        if document:
            _archive_original(file_path, document.requires_review)
    except Exception as e:
        logger.error(f"Failed to process document {file_path}: {e}")
    finally:
        db.close()


def _archive_original(file_path: Path, requires_review: bool) -> None:
    """Move processed scan into archive or review holding area."""
    try:
        source = file_path if file_path.is_absolute() else (SCAN_FOLDER_PATH / file_path)
        source = source.resolve()
        if not source.exists():
            logger.warning("Original file already moved or missing: %s", source)
            return

        target_base = (SCAN_REVIEW_HOLD_PATH if requires_review else SCAN_PROCESSED_PATH).resolve()
        target_base.mkdir(parents=True, exist_ok=True)
        destination = target_base / source.name
        counter = 1
        while destination.exists():
            destination = target_base / f"{source.stem}_{counter}{source.suffix}"
            counter += 1
        destination = destination.resolve()
        source.replace(destination)
    except Exception as exc:
        logger.warning("Failed to archive original scan %s: %s", file_path, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Related Education Document Server...")
    
    # Initialize database
    init_db()
    logger.info("Database initialized")
    
    # Set up file watcher
    file_watcher_service.set_process_callback(document_processor)
    
    # Process any existing files before starting the observer to avoid duplicates
    file_watcher_service.process_existing_files()
    file_watcher_service.start()
    
    logger.info(f"Watching for scans in: {SCAN_FOLDER_PATH}")
    logger.info(f"Storing documents in: {STORAGE_PATH}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    file_watcher_service.stop()


# Create FastAPI application
app = FastAPI(
    title="Related Education Document Server",
    description="A document management system for educational institutions",
    version="1.0.0",
    lifespan=lifespan
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Set up templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include routers
app.include_router(documents.router)
app.include_router(search.router)


# Web UI Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page."""
    db = SessionLocal()
    try:
        from app.models import Document
        recent_docs = db.query(Document).order_by(Document.created_at.desc()).limit(10).all()
        total_docs = db.query(Document).count()
        review_count = db.query(Document).filter(Document.requires_review.is_(True)).count()
        
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "recent_documents": recent_docs,
                "total_documents": total_docs,
                "review_count": review_count
            }
        )
    finally:
        db.close()


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    """Search page."""
    return templates.TemplateResponse(
        "search.html",
        {"request": request}
    )


@app.get("/review", response_class=HTMLResponse)
async def review_page(request: Request):
    """Manual review queue page."""
    return templates.TemplateResponse(
        "review.html",
        {"request": request}
    )


@app.get("/documents/{document_id}", response_class=HTMLResponse)
async def view_document(request: Request, document_id: str):
    """Document detail view page."""
    db = SessionLocal()
    try:
        from app.models import Document
        from uuid import UUID
        
        doc_uuid = UUID(document_id)
        document = db.query(Document).filter(Document.id == doc_uuid).first()
        
        if not document:
            return templates.TemplateResponse(
                "document_view.html",
                {"request": request, "document": None, "error": "Document not found"}
            )
        
        # Get number of pages for PDFs
        num_pages = 1
        if document.stored_path.endswith('.pdf'):
            from app.services.storage import storage_service
            previews = storage_service.get_preview_paths(document.stored_path)
            num_pages = len(previews) if previews else 1
        
        return templates.TemplateResponse(
            "document_view.html",
            {
                "request": request,
                "document": document,
                "num_pages": num_pages,
                "error": None
            }
        )
    finally:
        db.close()


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "scan_folder": str(SCAN_FOLDER_PATH),
        "storage_folder": str(STORAGE_PATH)
    }


if __name__ == "__main__":
    import uvicorn
    from app.config import HOST, PORT
    
    uvicorn.run(app, host=HOST, port=PORT)

