# API Reference

REST and web endpoints. All API routes are under `/api` unless noted. Auth is not implemented; assume internal/trusted network or add auth as needed.

## Web (HTML)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Home page (recent docs, totals, review count) |
| GET | `/search` | Search UI |
| GET | `/review` | Manual review queue UI |
| GET | `/documents/{document_id}` | Document detail view (UUID) |
| GET | `/health` | Health check (status, scan_folder, storage_folder) |

---

## Documents

Base path: **`/api/documents`**

### List documents

- **GET** `/api/documents`
- **Query**: `page` (default 1), `page_size` (default 20)
- **Response**: `DocumentListResponse` (documents, total, page, page_size)

### List review queue

- **GET** `/api/documents/review-queue`
- **Query**: `page`, `page_size`
- **Response**: `DocumentListResponse` (only documents with `requires_review=true`)

### Upload (manual)

- **POST** `/api/documents/upload/manual`
- **Body**: multipart form with `file` (required), optional `document_type` (`poe` | `certificate`). If omitted, type is detected from OCR (“Certificate issued” → certificate, else poe).
- **Response**: `DocumentResponse` (created document)

### Get document

- **GET** `/api/documents/{document_id}`
- **Params**: `document_id` (UUID)
- **Response**: `DocumentResponse`  
- **Errors**: 404 if not found

### Update document

- **POST** `/api/documents/{document_id}`
- **Params**: `document_id` (UUID)
- **Body**: `DocumentUpdate` (any subset of course_name, student_name, assignment_name, grade, document_date, document_type, student_id; optional requires_review, review_reason)
- **Response**: `DocumentResponse`  
- **Side effects**: Recomputes review status; may move file between review and final storage; may delete original from `_review_queue` when moving to final.
- **Errors**: 404 if not found

### Delete document

- **DELETE** `/api/documents/{document_id}`
- **Params**: `document_id` (UUID)
- **Response**: `{ "message": "Document deleted successfully" }`
- **Side effects**: Deletes stored file and, if present, original in `_review_queue`.
- **Errors**: 404 if not found

### Download file

- **GET** `/api/documents/{document_id}/file`
- **Params**: `document_id` (UUID)
- **Response**: File download (original filename, `application/octet-stream`)
- **Errors**: 404 if document or file missing

### Page preview image

- **GET** `/api/documents/{document_id}/preview/{page_num}`
- **Params**: `document_id` (UUID), `page_num` (1-based)
- **Response**: JPEG image for that page (or main file for single image docs)
- **Errors**: 404 if document or page not found

---

## Search

Base path: **`/api/search`**

### Search documents

- **GET** `/api/search`
- **Query**:
  - `query` — full-text across student_name, course_name, assignment_name, student_id, ocr_text
  - `student_name`, `course_name`, `assignment_name`, `student_id` — optional filters (ILIKE)
  - `date_from`, `date_to` — optional date range (inclusive)
  - `page` (default 1), `page_size` (default 20, max 100)
- **Response**: `DocumentListResponse`

### List students

- **GET** `/api/search/students`
- **Query**: `query` (optional filter), `limit` (default 50, max 200)
- **Response**: `{ "students": ["Name1", "Name2", ...] }`

### List courses

- **GET** `/api/search/courses`
- **Query**: `query`, `limit`
- **Response**: `{ "courses": ["Course1", ...] }`

### List assignments

- **GET** `/api/search/assignments`
- **Query**: `query`, `course_name` (optional), `limit`
- **Response**: `{ "assignments": ["Assignment1", ...] }`

---

## Schemas (shapes)

### DocumentResponse

```json
{
  "id": "uuid",
  "course_name": "string | null",
  "student_name": "string | null",
  "assignment_name": "string | null",
  "grade": "string | null",
  "document_date": "YYYY-MM-DD | null",
  "document_type": "string | null",
  "student_id": "string | null",
  "original_filename": "string",
  "stored_path": "string",
  "ocr_text": "string | null",
  "extraction_confidence": "float | null",
  "requires_review": "boolean",
  "review_reason": "string | null",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

### DocumentUpdate (request body)

Any subset of:

- `course_name`, `student_name`, `assignment_name`, `grade`, `document_date`, `document_type`, `student_id` (optional)
- `requires_review`, `review_reason` (optional)

### DocumentListResponse

```json
{
  "documents": [ "<DocumentResponse>" ],
  "total": "int",
  "page": "int",
  "page_size": "int"
}
```

---

## Examples

**Upload a file (optional document type)**

```bash
curl -X POST http://localhost:8000/api/documents/upload/manual -F "file=@scan.pdf" -F "document_type=certificate"
```

**Update document and clear review**

```bash
curl -X POST "http://localhost:8000/api/documents/{uuid}" \
  -H "Content-Type: application/json" \
  -d '{"student_name":"Jane Doe","grade":"A"}'
```

**Search by student, student ID, and date range**

```bash
curl "http://localhost:8000/api/search?student_name=Jane&student_id=0501015513085&date_from=2025-01-01&date_to=2025-12-31"
```
