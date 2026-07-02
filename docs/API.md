# API Reference

REST and web endpoints. API routes are under `/api`. Auth is not implemented;
assume an internal/trusted network or add auth as needed.

## Web (HTML)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard: recent docs, totals, review count, single + bulk upload |
| GET | `/search` | Search UI |
| GET | `/review` | Manual review queue (shows AI status + errors) |
| GET | `/settings` | Document types manager + AI extraction settings |
| GET | `/documents/{document_id}` | Document detail / edit view (type-aware form) |
| GET | `/health` | Health check (status, scan_folder, storage_folder) |

---

## Documents — `/api/documents`

### List / review queue
- **GET** `/api/documents` — query `page`, `page_size` → `DocumentListResponse`.
- **GET** `/api/documents/review-queue` — same, filtered to `requires_review=true`.

### Upload (single)
- **POST** `/api/documents/upload/manual`
- Multipart: `file` (required), optional `document_type`.
- Runs the full cascade synchronously → `DocumentResponse`.

### Upload (bulk, streaming)
- **POST** `/api/documents/bulk-upload`
- Multipart: `file` (one file per call — the client uploads serially).
- Returns an **NDJSON stream** of stage events, one JSON object per line:
  - `{"stage": "identify"}` — detecting the document type
  - `{"stage": "ocr"}` — OCR reading (first N pages)
  - `{"stage": "ai"}` — vision AI reading (only if rules left gaps)
  - final: `{"stage": "done", "result": "approved"|"review", "document_id": "...", "document_type": "...", "student_name": "...", "ai_used": true|false, "extraction_error": null|"..."}`
  - or `{"stage": "error", "message": "..."}`
- Type is always auto-identified (no `document_type` field).

### Get / update / delete
- **GET** `/api/documents/{document_id}` → `DocumentResponse` (incl. `custom_fields`). 404 if missing.
- **POST** `/api/documents/{document_id}` — body `DocumentUpdate` (any subset of core fields + optional `custom_fields`). Recomputes review status; may move the file between review/final storage.
- **DELETE** `/api/documents/{document_id}` → `{"message": "..."}`. Deletes the stored file, custom values, and any review-queue original.

### Files
- **GET** `/api/documents/{document_id}/file` — download the stored file.
- **GET** `/api/documents/{document_id}/preview/{page_num}` — JPEG preview for a page (1-based).

---

## Document types — `/api/document-types`

Configurable types and their fields (drive the review form, upload dropdown,
and extraction).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/document-types` | Active types with enriched fields (for forms) |
| GET | `/api/document-types/manage` | All types incl. inactive + `is_active`, `sort_order`, `max_pages` (admin) |
| GET | `/api/document-types/field-library` | Core fields available to add + supported `data_types` |
| GET | `/api/document-types/{key}/usage` | `{ "key", "count" }` — documents using this type (for the delete warning) |
| POST | `/api/document-types` | Create a type (`DocumentTypeIn`) |
| PUT | `/api/document-types/{key}` | Update label / fields / order / active / `max_pages` |
| DELETE | `/api/document-types/{key}` | Hard-delete a type |

**Field** (in a type): `{ key, label?, data_type?, required, visible }`.
Core fields (student_name, course_name, assignment_name, grade, document_date,
student_id) map to columns; any other key is a **custom** field (stored typed
in `document_field_values`). `data_type` ∈ `text` | `number` | `date` | `id`.

---

## Settings — `/api/settings`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings/ai` | Current AI config (API key never returned — only `api_key_set`) |
| PUT | `/api/settings/ai` | Update `enabled`, `provider`, `model`, `base_url`, `api_key` (blank key keeps the existing one) |
| POST | `/api/settings/ai/test` | Test connectivity to the model → `{ ok, message, model, response, latency_ms }` |

---

## Search — `/api/search`

### Search documents
- **GET** `/api/search`
- Query: `query` (full-text across student/course/assignment/student_id/OCR
  text **and custom field values**), `student_name`, `course_name`,
  `assignment_name`, `student_id`, `date_from`, `date_to`, `page`,
  `page_size` → `DocumentListResponse`.

### Autocomplete
- **GET** `/api/search/students` — `{ "students": [...] }`
- **GET** `/api/search/courses` — `{ "courses": [...] }`
- **GET** `/api/search/assignments` — query `course_name` optional — `{ "assignments": [...] }`

---

## MCP server (agent tools)

The `mcp_server/` package exposes the API to AI agents over the Model Context
Protocol (stdio). It is a thin client over the REST endpoints above — it holds
no state and enforces nothing the API doesn't. Target server is set with the
`RDS_BASE_URL` env var (default `http://192.168.88.25:8000/`). Setup and client
config are in [../mcp_server/README.md](../mcp_server/README.md).

**Scope:** read + add + edit only. There is **no delete tool**, AI config is
read-only (+ a connection test), and uploads take local file paths.

| Tool | Args | Wraps | Returns |
|------|------|-------|---------|
| `search_documents` | `query?`, `student_name?`, `course_name?`, `assignment_name?`, `student_id?`, `date_from?`, `date_to?`, `page?`, `page_size?` | `GET /api/search` | Paginated list of document summaries + `total`. |
| `list_recent_documents` | `page?`, `page_size?` | `GET /api/documents` | Recent documents (newest first). |
| `get_document` | `document_id` | `GET /api/documents/{id}` | Full record incl. custom fields + OCR text. |
| `get_document_preview` | `document_id`, `page?` | `GET /api/documents/{id}/preview/{page}` | Page image (so the agent can read the scan). |
| `upload_document` | `file_path`, `document_type?` | `POST /api/documents/upload/manual` | Processed document summary. |
| `bulk_upload_documents` | `file_paths[]` | `POST /api/documents/bulk-upload` (looped, serial) | Per-file results + approved/review/failed counts. |
| `list_review_queue` | `page?`, `page_size?` | `GET /api/documents/review-queue` | Documents needing review, each with its reason. |
| `update_document` | `document_id`, any of `student_name?`, `course_name?`, `assignment_name?`, `grade?`, `document_date?`, `document_type?`, `student_id?`, `custom_fields?` | `POST /api/documents/{id}` | Updated document (review status recomputed). |
| `list_document_types` | — | `GET /api/document-types` | Type + field schema (keys, data types, required, `max_pages`). |
| `get_ai_status` | — | `GET /api/settings/ai` | AI config (key never exposed, only `api_key_set`). |
| `test_ai_connection` | — | `POST /api/settings/ai/test` | `{ ok, message, model, response, latency_ms }`. |
| `server_health` | — | `GET /health` | `{ reachable, base_url, health }` (clear message if unreachable). |

Document summaries omit the full OCR text and stored path for readability; call
`get_document` for the complete record.

## Schemas

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
  "custom_fields": { "field_key": "value" },
  "original_filename": "string",
  "stored_path": "string",
  "ocr_text": "string | null",
  "extraction_confidence": "float | null",
  "ai_used": "boolean",
  "extraction_error": "string | null",
  "requires_review": "boolean",
  "review_reason": "string | null",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

### DocumentUpdate (request)
Any subset of `course_name`, `student_name`, `assignment_name`, `grade`,
`document_date`, `document_type`, `student_id`; plus optional `custom_fields`
(object keyed by custom field key), `requires_review`, `review_reason`.

### DocumentTypeIn (request)
`{ key?, label, sort_order, is_active, max_pages?, fields: [FieldConfigIn] }`
where `FieldConfigIn = { key, label?, data_type?, required, visible }`.

### DocumentListResponse
`{ "documents": [DocumentResponse], "total": int, "page": int, "page_size": int }`

---

## Examples

**Single upload**
```bash
curl -X POST http://localhost:8000/api/documents/upload/manual \
  -F "file=@scan.pdf" -F "document_type=certificate"
```

**Bulk upload (stream a file's stages)**
```bash
curl -N -X POST http://localhost:8000/api/documents/bulk-upload -F "file=@scan.pdf"
```

**Update core + custom fields**
```bash
curl -X POST "http://localhost:8000/api/documents/{uuid}" \
  -H "Content-Type: application/json" \
  -d '{"student_name":"Jane Doe","custom_fields":{"certificate_number":"QAP 617/2025/110249"}}'
```

**Test the AI connection**
```bash
curl -X POST http://localhost:8000/api/settings/ai/test \
  -H "Content-Type: application/json" \
  -d '{"provider":"openai","model":"gpt-4o-mini"}'
```
