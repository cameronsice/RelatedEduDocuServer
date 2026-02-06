# Style Guide

Conventions for code and docs in this project.

## Naming

- **Variables / functions**: `snake_case` (e.g. `document_id`, `get_document`, `process_document`).
- **Classes**: `PascalCase` (e.g. `Document`, `StorageService`, `DocumentHandler`).
- **Constants**: `UPPER_SNAKE_CASE` (e.g. `REQUIRED_FIELDS`, `CONFIDENCE_THRESHOLD`, `ALLOWED_DOCUMENT_TYPES`, `SCAN_FOLDER_PATH`).
- **Files / modules**: `snake_case` (e.g. `documents.py`, `ai_extractor.py`, `file_watcher.py`).
- **Folders**: `snake_case` (e.g. `app/routers`, `app/services`).
- **Branches**: kebab-case or snake_case (e.g. `feature/review-queue`, `fix/ocr-pdf`).

## Formatting / Lint

- **Python**: Follow PEP 8; line length can be 88–100 if the team uses Black. Use 4 spaces, no tabs.
- **Imports**: Standard library first, then third-party, then `app.*`; one group per block.
- **Docstrings**: Prefer triple-quoted; describe purpose, args, returns, and notable behavior where helpful.

## Folder & File Patterns

- **Routers**: `app/routers/<domain>.py` (e.g. `documents.py`, `search.py`); prefix routes with `/api/<domain>`.
- **Services**: `app/services/<name>.py`; one main class or module-level functions; instantiate once (e.g. `storage_service`, `ocr_service`).
- **Templates**: `app/templates/*.html`; Jinja2; base template for layout, others extend or include.
- **Static**: `static/css`, `static/js`, `static/images`; mounted at `/static`.

## Comments & Docs

- Use comments for non-obvious logic (e.g. why we wait for file write, why we use a counter suffix when moving).
- In API code, use FastAPI `description` on parameters and docstrings on route handlers.
- Markdown docs: concise bullets and tables; use code blocks for examples and config.

## Preferred Patterns

- **DB**: Use `Depends(get_db)` for session; avoid holding sessions across async boundaries; close or use context in lifespan/callbacks.
- **Configuration**: Read from env in `app/config.py`; resolve paths once at import; no env reads inside services.
- **Errors**: Use `HTTPException` with appropriate status codes; log at warning/error before raising where useful.
- **Router tags**: Use `tags=["documents"]` / `tags=["search"]` for OpenAPI grouping.
