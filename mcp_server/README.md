# Related Document Server — MCP Server

An [MCP](https://modelcontextprotocol.io) server that lets AI agents work with
the Related Document Server: search and read documents, upload single files or
batches, work the review queue, and inspect the type schema and AI status.

It is a thin **stdio** client over the existing REST API. It talks to a running
document server — by default the live one at `http://192.168.88.25:8000/`.

## Tools

| Tool | What it does |
|------|--------------|
| `search_documents` | Full-text + per-field search (student, course, assignment, ID, date range), paginated. |
| `list_recent_documents` | Most recently processed documents. |
| `get_document` | Full record for one document (all fields, review status, OCR text). |
| `get_document_preview` | Rendered image of a page, so the agent can read the scan. |
| `upload_document` | Upload one local file; runs the full extraction cascade. |
| `bulk_upload_documents` | Upload many local files, processed one at a time; per-file result summary. |
| `list_review_queue` | Documents needing review, each with its reason / AI error. |
| `update_document` | Correct/fill core + custom fields; recomputes review status (resolves out of the queue). |
| `list_document_types` | The type + field schema — read this before filling fields. |
| `get_ai_status` | Current AI config (read-only; key never exposed). |
| `test_ai_connection` | Ping the configured AI model; returns response + latency. |
| `server_health` | Check the server is reachable and show the target URL. |

Uploads take **absolute file paths** on the machine running this MCP server.
There is intentionally **no delete tool** — the live server holds real data.

## Install

From the project root:

```powershell
venv\Scripts\python.exe -m pip install -r mcp_server\requirements.txt
```

(`httpx` is already present via the web app; `mcp` is the only new dependency.)

## Configuration

Set via environment variables:

| Variable | Default | Meaning |
|----------|---------|---------|
| `RDS_BASE_URL` | `http://192.168.88.25:8000/` | Document server to connect to. |
| `RDS_TIMEOUT` | `180` | HTTP timeout in seconds (extraction can be slow). |

## Connect it to a client

### Claude Desktop / Claude Code

Add to your MCP config (e.g. `claude_desktop_config.json`), pointing at the
project's venv Python so dependencies resolve:

```json
{
  "mcpServers": {
    "related-documents": {
      "command": "C:\\Users\\User\\Documents\\RelatedDocumentServer\\venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server.server"],
      "cwd": "C:\\Users\\User\\Documents\\RelatedDocumentServer",
      "env": {
        "RDS_BASE_URL": "http://192.168.88.25:8000/"
      }
    }
  }
}
```

For Claude Code you can instead run:

```powershell
claude mcp add related-documents --env RDS_BASE_URL=http://192.168.88.25:8000/ -- C:\Users\User\Documents\RelatedDocumentServer\venv\Scripts\python.exe -m mcp_server.server
```

Restart the client; the tools appear under **related-documents**.

## Verify

```powershell
# From the project root, with the document server running:
venv\Scripts\python.exe -m mcp_server.server   # starts stdio server (Ctrl-C to stop)
```

Once connected in a client, ask it to run `server_health` — it should report
`reachable: true` and the base URL it's pointed at.
```
