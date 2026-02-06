# TODO

Prioritized backlog. Use `[ ]` Todo, `[x]` Done, `[>]` In progress.

## Features

- [ ] Add authentication / API key or basic auth for API and web
- [ ] Export documents or search results (CSV/Excel)
- [ ] Bulk actions (e.g. mark multiple as reviewed, bulk delete)
- [ ] Configurable required fields and confidence threshold per deployment
- [ ] Webhook or notification when documents enter review queue

## Bugs / Fixes

- [ ] (Add items as discovered)

## Refactors / Tech

- [ ] Add integration tests for document upload and review flow
- [ ] Add OpenAPI examples in FastAPI route docs
- [ ] Consider moving file-watcher processing to a background task/queue for scalability
- [ ] Add database migrations (e.g. Alembic) for schema changes

## Current status

- [x] Core docs initialized (README, ARCHITECTURE, STYLEGUIDE, API, TODO, NOTES)
- [x] Document type (POE / Certificate) with upload dropdown and OCR auto-detect
- [x] Student ID field (13-digit), AI + regex extraction, searchable
- [x] Descriptive stored filenames (StudentName_CourseName_Type_Last4.ext)
- [ ] (Update here with current sprint or focus)
