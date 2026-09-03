# TODO

Prioritized backlog. Use `[ ]` Todo, `[x]` Done, `[>]` In progress.

## Features

- [ ] Authentication / API key for API and web (currently open; internal use).
- [ ] Export documents or search results (CSV/Excel).
- [ ] Bulk actions in the UI (mark reviewed, bulk delete).
- [ ] Configurable confidence threshold per deployment (required fields are
      already per-type via Settings).
- [ ] Webhook / notification when documents enter the review queue.

## Extraction / AI

- [x] Make type **identification** more robust — per-type filename patterns and
      detection keywords, with an AI classification fallback. (Was a hardcoded
      keyword heuristic.) Remaining idea: per-type detection keywords
      configured in Settings, keyword scoring, or an AI-assisted identify step.
- [ ] Optional shared **field library** (reuse custom fields across types).
- [ ] Search/filter UI for custom fields (values are already stored + indexed).

## Refactors / Tech

- [ ] Add integration tests for the cascade, upload, and review flows.
- [ ] Add database migrations (Alembic) instead of `init_db` DDL.
- [ ] Consider a job queue for processing at scale (bulk is currently serial
      in-process).
- [ ] Pin `fastapi`/`starlette` versions in `requirements.txt`.

## Done

- [x] Rebrand to "Related Document Server" (logo mark, titles, favicon, footer).
- [x] Configurable document types + fields, managed on a `/settings` page
      (create/edit/delete, custom fields, per-type required/visible, max pages).
- [x] Per-field data types (text/number/date/id) + typed custom value store.
- [x] Type-aware review (only a type's required fields are checked).
- [x] Extraction cascade: OCR → rules → vision AI fallback → review.
- [x] Rules extractor: SA-ID Luhn checksum, date parsing, label-anchored fields.
- [x] Vision AI extraction for handwriting; per-type page caps.
- [x] Runtime AI config (provider/model/key/base URL) with Test Connection.
- [x] AI-failure visibility (review queue badge + error; "Rules only"/"Rules + AI").
- [x] Bulk upload with live per-file stage streaming.
- [x] SQLite local-dev mode; additive/self-healing migrations.
- [x] Documentation moved to `docs/` and updated.
- [x] MCP server (`mcp_server/`) wrapping the REST API: search, read, upload
      (single + bulk), review-queue correction, type schema + AI diagnostics.
