# Style Guide

Conventions for code and docs in this project.

## Naming

- **Variables / functions**: `snake_case` (e.g. `document_id`, `process_document`).
- **Classes**: `PascalCase` (e.g. `Document`, `RulesExtractor`, `DocumentTypeService`).
- **Constants**: `UPPER_SNAKE_CASE` (e.g. `CORE_FIELDS`, `CONFIDENCE_THRESHOLD`,
  `FIELD_DATA_TYPES`, `TESSERACT_CMD`).
- **Files / modules & folders**: `snake_case` (`rules_extractor.py`, `app/services`).
- **Branches**: kebab-case or snake_case (`feature/bulk-upload`, `fix/ocr-pdf`).

## Formatting / Lint

- **Python**: PEP 8; 4 spaces, no tabs; line length ~88–100.
- **Imports**: standard library, then third-party, then `app.*`; one group per block.
- **Docstrings**: triple-quoted; describe purpose, args, returns, notable behavior.

## Folder & File Patterns

- **Routers**: `app/routers/<domain>.py`; prefix routes `/api/<domain>`
  (`documents`, `search`, `document_types`, `settings`).
- **Services**: `app/services/<name>.py`; one main class or module-level
  functions; instantiate a single shared instance (e.g. `rules_extractor`,
  `vision_extractor`, `document_type_service`, `settings_service`).
- **Templates**: `app/templates/*.html`; Jinja2; `base.html` is the layout.
  Use the current `TemplateResponse(request, "name.html", context)` signature.
- **Static**: `static/css`, `static/js`, `static/images`; mounted at `/static`.

## Preferred Patterns

- **DB**: use `Depends(get_db)` in request handlers; the bulk worker and file
  watcher create their own `SessionLocal()` per unit of work and close it.
- **Configuration**: read env in `app/config.py`; resolve paths once at import.
  Runtime-tunable settings (AI provider/model/key) live in `app_settings` and
  are read via `settings_service`, not env, at call time.
- **Types & fields**: never hardcode document types or field lists — read them
  from `document_type_service`. Core fields live in `CORE_FIELDS`; custom
  fields are stored in `document_field_values` via `field_values`.
- **Extractors** return plain data: `rules_extractor.extract(...)` →
  `{field_key: value}`; `vision_extractor.extract(...)` →
  `{"values": {...}, "confidence": float, "error": str|None}`.
- **LLM calls** go through `app/services/llm.safe_chat_completion` so model
  parameter differences are handled in one place.
- **Errors**: raise `HTTPException` with appropriate status codes; log before
  raising where useful. Never silently swallow AI errors — surface them.
- **Migrations**: additive only. Add columns via `ADD COLUMN IF NOT EXISTS`
  (Postgres) or the SQLite self-heal in `init_db`; never drop or rewrite data.

## Comments & Docs

- Comment non-obvious logic (why a page cap, why the ID checksum, why rules win
  over AI on merge).
- API code: FastAPI `description=` on params and docstrings on handlers.
- Markdown docs live in `docs/` (except `README.md`); keep them concise with
  tables and code blocks. Update `docs/CHANGELOG.md` with notable changes.
