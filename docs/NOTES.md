# Notes

Gotchas, decisions, and references.

## Gotchas

- **External tools (Tesseract & Poppler)** must be installed on the host — they
  are not Python packages. On Windows, set `TESSERACT_CMD` and `POPPLER_PATH`
  in `.env` to the explicit binary / bin-dir paths so the server finds them
  even when they aren't on the process `PATH`. If unset, `PATH` is used.
- **AI is a fallback, not a default** — the vision model only runs when the
  rules tier can't fill every required field. A clean printed certificate is
  handled entirely by rules (no AI call, no PII sent externally).
- **Model parameter compatibility** — newer models (GPT-5 / o-series) require
  `max_completion_tokens` and may reject `temperature`. `app/services/llm.py`
  (`safe_chat_completion`) adapts automatically based on the API error, so both
  old and new models work. Use the **Test Connection** button on Settings to
  verify a model before relying on it.
- **AI failures are surfaced, not hidden** — a failed AI call sets
  `extraction_error`, forces review, and prefixes the review reason with
  "AI extraction failed". The review queue shows an "AI error" badge (full
  error on hover) and the document view shows a red alert.
- **Page caps** — each type's `max_pages` limits both OCR and the images sent
  to AI (Certificate 1, POE 5). POEs are many pages but the useful cover data
  is in the first few.
- **Handwriting** — Tesseract is unreliable on handwriting; that's exactly what
  the vision tier is for. Rules deliberately return *nothing* rather than a
  wrong guess, so handwritten fields escalate to AI or review.
- **Student ID** — extracted by rules (13-digit regex) and validated with a
  Luhn checksum + date-of-birth sanity check. An AI-provided ID that fails the
  checksum is discarded. Student ID is required for POE and Certificate.
- **Bulk upload is serial** — the browser uploads one file at a time and streams
  each file's stages, so the server processes one document at a time.
- **Review queue file cleanup** — moving a document from review to final tries
  to remove the original from the scan `_review_queue` folder, matching by name
  or `stem_counter`; a missing original is skipped without failing.
- **Descriptive filenames** — after extraction the stored file is renamed to
  `Student_Course_Type_Last4.ext` (sanitized; collisions get `_1`, `_2`, …).

## Design decisions

- **Review status** — a document needs review if any *required field for its
  type* is missing, if AI confidence is below threshold (0.6), or if the AI
  call errored. Required fields are per type (e.g. Certificate needs no grade
  or assignment; POE grade is optional).
- **Types & fields are data** — stored in `document_types` and edited on the
  Settings page. Custom fields are typed and stored in `document_field_values`
  (not on the `documents` table), keeping existing data stable and every field
  searchable. See [ARCHITECTURE.md](ARCHITECTURE.md).
- **AI provider is runtime config** — provider/model/API key/base URL live in
  `app_settings` and are editable in the UI. Base URL lets you point at a
  local/self-hosted OpenAI-compatible endpoint to keep data on-premises.
- **Additive migrations only** — `init_db()` never drops or rewrites data. New
  columns are added via `ADD COLUMN IF NOT EXISTS` (Postgres) or a
  PRAGMA-checked `ALTER TABLE` self-heal (SQLite).
- **Local dev** — SQLite via `DATABASE_URL=sqlite:///./education_docs.db`; no
  Postgres/OpenAI required to browse the UI. Production uses PostgreSQL.

## POPIA / privacy

Student names and 13-digit SA ID numbers are sensitive personal information.
Sending scans to an overseas cloud AI is a cross-border transfer under POPIA.
Mitigations built in: rules-first (AI rarely runs), per-type page caps (data
minimization), and a configurable **Base URL** so a local/self-hosted model can
process everything on-premises. Using a cloud provider should be paired with an
operator/data-processing agreement.

## References

- [FastAPI](https://fastapi.tiangolo.com/)
- [Tesseract](https://github.com/tesseract-ocr/tesseract) · [UB-Mannheim Windows build](https://github.com/UB-Mannheim/tesseract/wiki)
- [Poppler for Windows](https://github.com/oschwartz10612/poppler-windows/releases)
- [Watchdog](https://github.com/gorakhargosh/watchdog)
