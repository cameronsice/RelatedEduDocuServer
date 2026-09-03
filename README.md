# Related Document Server

A document management system that automatically processes scanned student
documents, extracts key fields with a rules-first / AI-fallback cascade, and
provides a searchable web interface and REST API.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design, the extraction cascade, data model
- [docs/API.md](docs/API.md) — REST + web API reference
- [docs/STYLEGUIDE.md](docs/STYLEGUIDE.md) — naming, formatting, patterns
- [docs/NOTES.md](docs/NOTES.md) — gotchas, decisions, POPIA, references
- [docs/TODO.md](docs/TODO.md) — backlog and status
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — version history
- [mcp_server/README.md](mcp_server/README.md) — MCP server for AI agents
- [DEPLOY.md](DEPLOY.md) — deploy/upgrade runbook for the live server (data-safe)

## Features

- **Configurable document types** — types and their fields are data, managed on
  the Settings page (create/edit/delete types, add core or custom fields, set
  required/visible, per-type max pages). Ships with POE and Certificate.
- **Typed fields** — every field is `text` / `number` / `date` / `id`; custom
  field values are stored typed and are searchable.
- **Extraction cascade** — OCR (Tesseract, page-capped) → deterministic rules
  → AI fallback (OCR text first, page images only if still needed; only when
  rules leave gaps) → review queue. Daily AI call limit and per-call caps
  bound cost.
  - Rules: SA-ID Luhn checksum, date parsing, label-anchored fields.
  - Vision AI reads page images directly, so it handles handwriting.
- **Runtime AI config** — provider, model, API key and base URL are set in the
  UI (not `.env`), with a **Test Connection** button. Base URL supports
  local/self-hosted models to keep data on-premises (POPIA).
- **Bulk upload** — select many mixed files; each is processed one at a time
  with a live per-file queue (Uploading → Identify → OCR → AI → Approved/Review).
- **Review queue** — flags documents missing required fields, with low AI
  confidence, or with a visible **AI error**; shows whether the AI tier ran.
- **Automatic ingestion** — a watched scan folder feeds the same cascade.
- **Descriptive filenames**, image optimization, PDF previews, full-text search.
- **MCP server for AI agents** — a stdio MCP server (`mcp_server/`) wraps the
  REST API so agents can search, upload (single + bulk), work the review queue,
  and read the type schema. See [mcp_server/README.md](mcp_server/README.md).

## Prerequisites

- Python 3.10+
- Tesseract OCR and Poppler (system installs — see below)
- PostgreSQL 13+ (production) — or SQLite for local development
- An OpenAI, Anthropic, xAI or other OpenAI-compatible API key, or a local model (optional; only used as the
  extraction fallback)

### Installing Tesseract & Poppler

**Windows (winget):**
```powershell
winget install UB-Mannheim.TesseractOCR
winget install oschwartz10612.Poppler
```
Then set explicit paths in `.env` (see Configuration) so the server finds them.

**Linux:** `sudo apt-get install tesseract-ocr poppler-utils`
**macOS:** `brew install tesseract poppler`

## Installation

```bash
git clone <repository-url>
cd RelatedDocumentServer
python -m venv venv
venv\Scripts\activate        # Windows  (source venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
copy .env.example .env        # then edit .env
```

Run:
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Open http://localhost:8000.

## Configuration

Edit `.env` (see `.env.example`):

- **Database** — `DATABASE_URL`. Local dev: `sqlite:///./education_docs.db`
  (no external services needed). Production: `postgresql+psycopg://...`.
- **Folder paths** — `SCAN_FOLDER_PATH`, `SCAN_PROCESSED_PATH`,
  `SCAN_REVIEW_HOLD_PATH`, `STORAGE_PATH`, `STORAGE_REVIEW_PATH` (relative paths
  resolve against the project root).
- **External tools (Windows)** — `TESSERACT_CMD` (path to `tesseract.exe`) and
  `POPPLER_PATH` (Poppler `bin` dir). Leave blank to use `PATH`.
- **AI** — configure the provider, model, API key and base URL on the
  **Settings** page in the app (stored in the DB). `OPENAI_API_KEY` in `.env`
  is used as a fallback if set.

## Usage

1. Open http://localhost:8000.
2. **Settings** → configure AI (provider/model/key), test the connection, and
   manage document types + fields.
3. Upload a document (single) or several (bulk), or drop files in the scan
   folder. Each flows through the cascade.
4. Work the **Review Queue** for anything incomplete; save to move it to final
   storage. **Search** by student, course, assignment, ID, custom field, or date.

## Project Structure

```
RelatedDocumentServer/
├── app/
│   ├── main.py                 # FastAPI app, web routes, lifespan
│   ├── config.py               # Env settings, external-tool paths
│   ├── database.py             # Engine, sessions, init_db migrations
│   ├── models.py               # documents, document_types, document_field_values, app_settings
│   ├── schemas.py              # Pydantic schemas
│   ├── routers/                # documents, search, document_types, settings
│   ├── services/               # storage, ocr, rules_extractor, ai_extractor, llm,
│   │                           #   ai_extractor, llm, document_types, field_values,
│   │                           #   settings, file_watcher
│   └── templates/              # Jinja2 templates
├── static/                     # CSS, JS, images (logo)
├── mcp_server/                 # MCP server for AI agents (stdio, wraps the REST API)
├── docs/                       # Architecture, API, etc.
├── .env.example
└── requirements.txt
```

## License

MIT License
