# Related Education Document Server

A document management system for educational institutions that automatically processes scanned student documents, extracts key information using OCR and AI, and provides a searchable web interface.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — System design, modules, data flow
- [STYLEGUIDE.md](STYLEGUIDE.md) — Naming, formatting, patterns
- [API.md](API.md) — REST API reference
- [TODO.md](TODO.md) — Backlog and status
- [NOTES.md](NOTES.md) — Gotchas, decisions, references
- [CHANGELOG.md](CHANGELOG.md) — Version history

## Features

- **Automatic Document Processing**: Monitors a network folder for new scanned documents
- **OCR Text Extraction**: Uses Tesseract to extract text from scanned images and PDFs
- **AI-Powered Field Extraction**: Uses OpenAI GPT to extract structured data:
  - Course Name
  - Student Name
  - Assignment Name
  - Grade
  - Date
  - Student ID (13-digit government ID; regex fallback if AI misses it)
- **Document Types**: POE (Grade Books) and Certificates. Type can be chosen on upload or auto-detected from OCR (“Certificate issued” → certificate).
- **Descriptive Stored Filenames**: Processed files are renamed to `StudentName_CourseName_Type_Last4ID.ext` (e.g. `John_Doe_Math_poe_3085.pdf`).
- **Manual Review Queue**: Automatically flags documents with missing fields or low AI confidence, routes them into separate “pending” storage, and shows the reason they need review.
- **Safe Deletions & Archival**: The watch folder is kept clean (processed scans are moved to archive/review holding areas) and you can remove documents + stored files directly from the dashboard.
- **Image Optimization**: Compresses and stores documents efficiently
- **Web Interface**: Search and view documents by student, course, assignment, student ID, or keyword
- **REST API**: Full programmatic access to all functionality

## Prerequisites

- Python 3.10+
- PostgreSQL 13+
- Tesseract OCR installed on the system
- Poppler (for PDF processing)

### Installing Tesseract

**Windows:**
Download and install from: https://github.com/UB-Mannheim/tesseract/wiki

**Linux:**
```bash
sudo apt-get install tesseract-ocr
```

**macOS:**
```bash
brew install tesseract
```

### Installing Poppler (for PDF support)

**Windows:**
Download from: https://github.com/oschwartz10612/poppler-windows/releases

**Linux:**
```bash
sudo apt-get install poppler-utils
```

**macOS:**
```bash
brew install poppler
```

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd RelatedEduDocuServer
```

2. Create a virtual environment:
```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/macOS
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Copy the environment file and configure:
```bash
copy .env.example .env  # Windows
cp .env.example .env  # Linux/macOS
```

5. Edit `.env` with your configuration:
   - Set your PostgreSQL connection string
   - Add your OpenAI API key
   - Configure folder paths (all optional; defaults are shown)
     ```
     SCAN_FOLDER_PATH=./scans
     SCAN_PROCESSED_PATH=./scans/_processed
     SCAN_REVIEW_HOLD_PATH=./scans/_review_queue
     STORAGE_PATH=./storage
     STORAGE_REVIEW_PATH=./storage/review_queue
     ```
     > All paths are resolved to absolute locations, so relative values are allowed.

6. Create the database:
```bash
# In PostgreSQL
CREATE DATABASE education_docs;
```

7. Run the application:
```bash
python -m uvicorn app.main:app --reload
```

## Usage

1. Access the web interface at `http://localhost:8000`
2. Place scanned documents in the configured scan folder
3. The system will automatically process new documents and move originals to `/scans/_processed` (or `_review_queue` if more data is needed)
4. Use `/review` to work the manual queue—fill in missing fields, save, and the document (and optimized file) will move into final storage automatically
5. Search for documents by student name, course, assignment, or student ID; view/edit document type and student ID; view/download or delete records

## API Endpoints

- `GET /` - Home page
- `GET /search` - Search interface
- `GET /documents/{id}` - View document details
- `GET /api/documents` - List all documents
- `GET /api/documents/{id}` - Get document by ID
- `GET /api/search` - Search documents (query, student_name, course_name, assignment_name, student_id, date range)
- `POST /api/documents/upload/manual` - Upload document (optional `document_type`: poe | certificate)
- `POST /api/documents/{id}` - Update document fields
- `DELETE /api/documents/{id}` - Delete document

## Project Structure

```
RelatedEduDocuServer/
├── app/
│   ├── main.py              # FastAPI application entry
│   ├── config.py            # Configuration settings
│   ├── database.py          # PostgreSQL connection
│   ├── models.py            # SQLAlchemy models
│   ├── schemas.py           # Pydantic schemas
│   ├── routers/
│   │   ├── documents.py     # Document CRUD endpoints
│   │   └── search.py        # Search endpoints
│   ├── services/
│   │   ├── file_watcher.py  # Monitor scan folder
│   │   ├── ocr_service.py   # Tesseract OCR processing
│   │   ├── ai_extractor.py  # AI field extraction
│   │   └── storage.py       # File optimization & storage
│   └── templates/           # Jinja2 HTML templates
├── static/                  # CSS, JS assets
├── storage/                 # Optimized document storage
├── scans/                   # Input folder for scanned documents
└── requirements.txt
```

## License

MIT License

