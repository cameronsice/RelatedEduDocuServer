# Notes

Gotchas, decisions, and references.

## Gotchas

- **Scan folder**: The file watcher only picks up **new** files (created after the watcher starts). Existing files are processed once at startup via `process_existing_files()`; duplicates are avoided by the watcher’s in-memory set.
- **Review queue file cleanup**: When a document moves from “review” to “final” (user fills fields and saves), the code tries to delete the **original** file from `_review_queue`. It matches by name or by stem + counter (e.g. `doc_1.pdf`). If the original was already removed or renamed, the delete is skipped without failing.
- **Tesseract / Poppler**: Must be installed on the host; not Python packages. See README for install links (Windows: tesseract wiki, poppler-windows releases).
- **OpenAI**: Set `OPENAI_API_KEY` in `.env`. AI extraction is used for course/student/assignment/grade/date/student_id; if key is missing or extraction fails, documents may still be stored with empty or default fields and will typically land in the review queue. Student ID has a regex fallback (`\b\d{13}\b`) when AI does not return it.
- **Document type**: If not provided on manual upload, type is inferred from OCR: presence of “Certificate issued” (case-insensitive) → `certificate`, otherwise `poe`. Stored filename uses short labels `poe` / `certificate`.
- **Paths**: All configured paths are resolved to absolute at startup. Relative paths in `.env` are relative to the project base directory (`app/config.py` uses `BASE_DIR`).

## Design decisions

- **Review status**: A document needs review if any of the required fields (course_name, student_name, assignment_name, grade, document_date) is missing, or if extraction confidence is below the threshold (0.6). Once all are set (e.g. by manual edit), review is cleared even if confidence was low.
- **Storage layout**: Final storage uses date-based dirs (`YYYY/MM/DD`). Review storage uses a flat `review_queue` under the main storage path. PDFs get a subfolder with optimized images and optional PDF copy; see `app/services/storage.py`. After extraction, the stored file is **renamed** from UUID to a descriptive name: `StudentName_CourseName_poe|certificate_Last4.ext` (sanitized; collisions get `_1`, `_2`, …). Preview dir is renamed to match.
- **Single process**: No separate worker; file watcher and HTTP server run in one process. Fine for single-node; for scaling, consider moving processing to a queue (e.g. Celery, Redis queue).

## References

- [FastAPI](https://fastapi.tiangolo.com/)
- [Tesseract](https://github.com/tesseract-ocr/tesseract)
- [Poppler (pdf2image)](https://github.com/oschwartz10612/poppler-windows/releases) (Windows)
- [Watchdog](https://github.com/gorakhargosh/watchdog)
