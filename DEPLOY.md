# Deployment Runbook — upgrading the live Related Document Server

**Audience:** the agent/operator performing the upgrade **on the live server**
(`http://192.168.88.25:8000/`), which runs **PostgreSQL with real production
data**.

**Prime directive:** this upgrade must not lose or mutate existing data. Every
schema change in this codebase is **additive** (new tables + `ADD COLUMN IF NOT
EXISTS`); there are **no `DROP`, `DELETE`, or destructive `UPDATE` statements**
in the startup path. Verify that yourself (Step 0) before you trust it, then
still take a backup (Step 1). If any instruction here would drop, truncate, or
overwrite data, **stop and ask a human.**

---

## Step 0 — Verify the "additive only" claim yourself

Before touching production, read these and confirm they only *add*:

- `app/database.py` → `init_db()`. It runs `Base.metadata.create_all()` (creates
  missing tables only — never alters or drops existing ones) followed by
  Postgres `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT
  EXISTS` statements. The only `UPDATE`s backfill NULLs on **newly added**
  columns (`requires_review`, `document_type`) — they don't touch existing
  values. There are no `DROP`/`DELETE`/`TRUNCATE` statements.
- `grep -rin "drop table\|drop column\|truncate\|delete from" app/` finds no SQL
  data-loss statements. The only matches are harmless: a `# Delete from database`
  **comment** in `routers/documents.py` on the explicit `DELETE
  /api/documents/{id}` endpoint (deliberate user action, never run during
  deploy), and a `# Truncate text` **comment** in `ai_extractor.py` about
  trimming a string for token limits (not SQL `TRUNCATE`). Nothing in the
  startup/migration path deletes or drops.

If that all checks out, continue. If anything looks off, stop.

---

## Step 1 — Back up first (non-negotiable)

1. **Database dump** (adjust connection details to match the live `.env`
   `DATABASE_URL`):
   ```bash
   pg_dump "$DATABASE_URL" -Fc -f ~/rds-backup-$(date +%Y%m%d-%H%M%S).dump
   ```
   Confirm the file exists and is non-trivial in size.

2. **Stored document files** — the actual scans live under `STORAGE_PATH`
   (default `./storage`, incl. `storage/review_queue`) and the scan folders.
   Back up the storage tree:
   ```bash
   tar czf ~/rds-storage-$(date +%Y%m%d-%H%M%S).tgz storage scans
   ```

3. **Current code + env** — note the current commit and preserve `.env`:
   ```bash
   git rev-parse HEAD > ~/rds-previous-commit.txt   # for rollback
   cp .env ~/rds-env-backup                          # .env is NOT in git
   ```

Do not proceed until all three backups exist.

---

## Step 2 — What's changing in this release

**New database objects (all additive, created automatically on first startup):**

| Object | Type | Created by |
|--------|------|-----------|
| `document_types` | table | `create_all` (then seeded with POE + Certificate, idempotent) |
| `document_field_values` | table | `create_all` |
| `app_settings` | table | `create_all` |
| `documents.ai_used` | column | `ADD COLUMN IF NOT EXISTS` (default FALSE) |
| `documents.extraction_error` | column | `ADD COLUMN IF NOT EXISTS` |

(Older columns — `extraction_confidence`, `requires_review`, `review_reason`,
`document_type`, `student_id`, plus `ix_documents_student_id` — are also guarded
by `IF NOT EXISTS`, so re-running is safe whether or not they already exist.)

**New application code:**
- The **extraction cascade** (OCR → rules → vision-AI fallback → review) and
  configurable document types / typed custom fields.
- A new **`mcp_server/`** package (MCP server for AI agents). It is **optional**
  and independent of the web app — deploying the web app does not require it.

**Config / behavior changes to be aware of:**
- **AI config moved to the database** (Settings page → `app_settings`), editable
  at runtime. The existing `OPENAI_API_KEY` in `.env` still works as a
  **fallback**, so extraction keeps working immediately after deploy. After
  deploy, set provider/model on the **Settings** page and click **Test
  Connection**.
- **External tools required for processing:** Tesseract OCR and Poppler must be
  installed on this host (they are OS packages, not pip installs). If they were
  already installed for the old version, nothing to do. Otherwise:
  - Linux: `sudo apt-get install -y tesseract-ocr poppler-utils`
  - If they aren't on the process `PATH`, set `TESSERACT_CMD` and `POPPLER_PATH`
    in `.env` (see `.env.example`). These are **new optional** env vars; leaving
    them blank uses `PATH`.
- Missing Tesseract/Poppler only affects **new** processing, never existing
  records — but uploads would route to the review queue until it's fixed.

---

## Step 3 — Deploy

1. **Put the app in a safe state** (stop the running service, or take it out of
   rotation). Note how it's currently started (systemd unit, `uvicorn`, etc.) so
   you can restart it the same way.

2. **Pull the new code** onto a branch, preserving local `.env` (which is
   git-ignored and must not be overwritten):
   ```bash
   git fetch origin
   git status                      # confirm .env is untracked / no surprise local edits
   git checkout <target-branch-or-tag>   # e.g. main
   git pull --ff-only
   ```
   If `git pull` reports it would overwrite `.env` or anything under `storage/`,
   **stop** — those must be preserved.

3. **Install/refresh Python dependencies** (into the same venv the service uses):
   ```bash
   pip install -r requirements.txt
   ```
   Optionally, to also run the MCP server on this host:
   ```bash
   pip install -r mcp_server/requirements.txt
   ```

4. **Run the additive migration.** It runs automatically in the app's lifespan
   on startup (`init_db()` + type seeding). To run it explicitly first (so you
   can confirm it before serving traffic):
   ```bash
   python -c "from app.database import init_db; init_db()"
   python -c "from app.database import SessionLocal; from app.services.document_types import document_type_service; db=SessionLocal(); document_type_service.seed_defaults(db); db.close()"
   ```
   Both are idempotent — safe to run more than once.

5. **Start the service** the same way it ran before.

---

## Step 4 — Verify

Run these against the live server and confirm sane results:

```bash
# Health
curl -s http://192.168.88.25:8000/health

# Existing data is intact — total should match pre-deploy expectations
curl -s "http://192.168.88.25:8000/api/documents?page=1&page_size=1" | head

# New schema is live
curl -s http://192.168.88.25:8000/api/document-types | head
curl -s http://192.168.88.25:8000/api/settings/ai        # api_key_set should reflect the env fallback
```

Also confirm in the DB that **row counts are unchanged** from before the deploy
(compare `SELECT count(*) FROM documents;` against your pre-deploy number) and
that the new columns/tables exist:

```sql
SELECT count(*) FROM documents;                     -- unchanged
\d+ documents                                       -- has ai_used, extraction_error
\dt                                                 -- has document_types, document_field_values, app_settings
```

In the UI: open a couple of **existing** documents (fields intact), then process
one **new** test upload end-to-end (Settings → Test Connection first if AI is
used). Check the review queue renders.

---

## Step 5 — MCP server (optional, only if agents will use this host)

The MCP server is a separate stdio process; it does not change the web app.
See [mcp_server/README.md](mcp_server/README.md). In short: `pip install -r
mcp_server/requirements.txt`, then register it with the agent client pointing at
this server:
```
RDS_BASE_URL=http://192.168.88.25:8000/  python -m mcp_server.server
```

---

## Rollback

If verification fails and you need to revert:

1. Stop the service.
2. Check out the previous commit:
   ```bash
   git checkout $(cat ~/rds-previous-commit.txt)
   pip install -r requirements.txt      # restore old deps
   ```
3. The new **tables/columns are additive** — the old code simply ignores them,
   so you usually do **not** need to touch the database to roll back the code.
   Only if a DB restore is truly required:
   ```bash
   pg_restore --clean --if-exists -d "$DATABASE_URL" ~/rds-backup-<timestamp>.dump
   ```
   (`--clean` drops/recreates objects from the dump — this **overwrites current
   data with the backup**. Only do this if you accept losing anything written
   since the backup, and confirm with a human first.)
4. Restart the service on the old commit and re-verify `/health`.

---

## Notes / gotchas

- `.env` is not in the repo — the live values (real `DATABASE_URL`, folder
  paths, API key, Tesseract/Poppler paths) live only on this host. Never
  overwrite it during deploy.
- The review→final file-move fix only affects **future** moves; it does not
  retroactively relocate files already placed on disk by the old version.
- If OCR/AI seems to do nothing after deploy, it's almost always Tesseract/
  Poppler not found (check `TESSERACT_CMD` / `POPPLER_PATH`) or AI not
  configured (Settings → Test Connection) — not a data problem.
