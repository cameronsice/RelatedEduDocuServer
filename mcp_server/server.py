"""MCP server for the Related Document Server.

Exposes the document server's capabilities to AI agents over the Model Context
Protocol: search, read, upload (single + bulk), correct/review documents, and
inspect the type schema and AI status. It is a thin stdio client over the REST
API — configure the target with the ``RDS_BASE_URL`` environment variable
(defaults to the live server, ``http://192.168.88.25:8000/``).

Run:
    python -m mcp_server.server        # from the project root
    # or, installed:  related-docs-mcp
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP, Image

from mcp_server.client import BASE_URL, APIError, DocumentServerClient

mcp = FastMCP("related-document-server")

# One shared client for the process lifetime.
client = DocumentServerClient()


def _pretty(data: Any) -> str:
    """Serialize a result as readable JSON for the agent."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def _summarize_document(doc: dict) -> dict:
    """Trim a full DocumentResponse to the fields agents usually want.

    Drops bulky/rarely-needed fields (full OCR text, stored path) so lists stay
    readable. Use ``get_document`` for the complete record including OCR text.
    """
    keep = (
        "id",
        "document_type",
        "student_name",
        "student_id",
        "course_name",
        "assignment_name",
        "grade",
        "document_date",
        "custom_fields",
        "requires_review",
        "review_reason",
        "ai_used",
        "extraction_error",
        "original_filename",
        "created_at",
    )
    return {k: doc.get(k) for k in keep if k in doc}


# --------------------------------------------------------------------------
# Search & read
# --------------------------------------------------------------------------


@mcp.tool()
def search_documents(
    query: Optional[str] = None,
    student_name: Optional[str] = None,
    course_name: Optional[str] = None,
    assignment_name: Optional[str] = None,
    student_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Search documents.

    ``query`` is a full-text search across student name, course, assignment,
    student ID, OCR text, and custom field values. The other parameters filter
    by a specific field (substring match). ``date_from``/``date_to`` bound the
    document date (``YYYY-MM-DD``). Returns a paginated list of document
    summaries with a ``total`` count.
    """
    result = client.search(
        {
            "query": query,
            "student_name": student_name,
            "course_name": course_name,
            "assignment_name": assignment_name,
            "student_id": student_id,
            "date_from": date_from,
            "date_to": date_to,
            "page": page,
            "page_size": page_size,
        }
    )
    result["documents"] = [_summarize_document(d) for d in result.get("documents", [])]
    return _pretty(result)


@mcp.tool()
def list_recent_documents(page: int = 1, page_size: int = 20) -> str:
    """List the most recently processed documents (newest first), paginated."""
    result = client.list_documents(page=page, page_size=page_size)
    result["documents"] = [_summarize_document(d) for d in result.get("documents", [])]
    return _pretty(result)


@mcp.tool()
def get_document(document_id: str) -> str:
    """Get the full record for one document by its ID.

    Includes all core and custom fields, review status and reason, whether the
    AI tier ran, any extraction error, and the full OCR text.
    """
    return _pretty(client.get_document(document_id))


@mcp.tool()
def get_document_preview(document_id: str, page: int = 1) -> Image:
    """Return a rendered image of a document page (1-based) so you can read the
    actual scan. Useful to verify or hand-fill fields the extractor missed."""
    data = client.get_preview(document_id, page)
    return Image(data=data, format="jpeg")


# --------------------------------------------------------------------------
# Add documents
# --------------------------------------------------------------------------


@mcp.tool()
def upload_document(file_path: str, document_type: Optional[str] = None) -> str:
    """Upload a single local file and run the full extraction cascade.

    ``file_path`` is an absolute path on the machine running this MCP server.
    ``document_type`` optionally forces a type key (e.g. ``"poe"`` or
    ``"certificate"``); omit it to let the server auto-identify. Returns the
    processed document, including whether it was approved or routed to review.
    """
    doc = client.upload(Path(file_path), document_type=document_type)
    return _pretty(_summarize_document(doc))


@mcp.tool()
def bulk_upload_documents(file_paths: list[str]) -> str:
    """Upload many local files, processed one at a time (serially).

    Each file goes through the full cascade with auto-identified type. Returns a
    per-file result summary — type, key fields, whether it was approved or sent
    to review, whether AI ran, and any error — plus counts. Use this to ingest a
    batch and then review the outputs (see ``list_review_queue``).
    """
    results = []
    approved = review = failed = 0
    for raw in file_paths:
        path = Path(raw)
        try:
            event = client.bulk_upload(path)
        except APIError as exc:
            failed += 1
            results.append({"file": path.name, "result": "error", "error": str(exc)})
            continue

        stage = event.get("stage")
        if stage == "done":
            outcome = event.get("result")
            if outcome == "approved":
                approved += 1
            else:
                review += 1
            results.append(
                {
                    "file": path.name,
                    "result": outcome,
                    "document_id": event.get("document_id"),
                    "document_type": event.get("document_type"),
                    "student_name": event.get("student_name"),
                    "ai_used": event.get("ai_used"),
                    "extraction_error": event.get("extraction_error"),
                }
            )
        else:
            failed += 1
            results.append(
                {
                    "file": path.name,
                    "result": "error",
                    "error": event.get("message", "unknown error"),
                }
            )

    return _pretty(
        {
            "total": len(file_paths),
            "approved": approved,
            "needs_review": review,
            "failed": failed,
            "results": results,
        }
    )


# --------------------------------------------------------------------------
# Review queue
# --------------------------------------------------------------------------


@mcp.tool()
def list_review_queue(page: int = 1, page_size: int = 20) -> str:
    """List documents that need manual review, each with its review reason.

    A document lands here when a required field is missing, AI confidence was
    low, or the AI call errored (``extraction_error`` set). Correct it with
    ``update_document`` — filling the required fields moves it out of the queue.
    """
    result = client.review_queue(page=page, page_size=page_size)
    result["documents"] = [_summarize_document(d) for d in result.get("documents", [])]
    return _pretty(result)


@mcp.tool()
def update_document(
    document_id: str,
    student_name: Optional[str] = None,
    course_name: Optional[str] = None,
    assignment_name: Optional[str] = None,
    grade: Optional[str] = None,
    document_date: Optional[str] = None,
    document_type: Optional[str] = None,
    student_id: Optional[str] = None,
    custom_fields: Optional[dict[str, Any]] = None,
) -> str:
    """Correct or fill a document's fields.

    Pass only the fields you want to change; others are left untouched.
    ``document_date`` is ``YYYY-MM-DD``. ``custom_fields`` is an object keyed by
    the type's custom field keys (see ``list_document_types``); keys not defined
    for the document's type are ignored. Review status is recomputed — filling
    all required fields resolves the document out of the review queue and moves
    it to final storage. Returns the updated document.
    """
    payload = {
        "student_name": student_name,
        "course_name": course_name,
        "assignment_name": assignment_name,
        "grade": grade,
        "document_date": document_date,
        "document_type": document_type,
        "student_id": student_id,
        "custom_fields": custom_fields,
    }
    doc = client.update_document(document_id, payload)
    return _pretty(_summarize_document(doc))


# --------------------------------------------------------------------------
# Schema & diagnostics
# --------------------------------------------------------------------------


@mcp.tool()
def list_document_types() -> str:
    """List the configured document types and their fields.

    This is the schema to read before filling fields: each type lists its fields
    with ``key``, ``label``, ``data_type`` (text/number/date/id), whether the
    field is ``required``, and the type's ``max_pages``. Use these keys with
    ``upload_document`` (``document_type``) and ``update_document``
    (``custom_fields``)."""
    return _pretty(client.document_types())


@mcp.tool()
def get_ai_status() -> str:
    """Show the current AI extraction configuration (read-only).

    Returns whether AI is enabled, the provider, model, and base URL, and
    whether an API key is set. The API key value itself is never exposed."""
    return _pretty(client.ai_status())


@mcp.tool()
def test_ai_connection() -> str:
    """Test connectivity to the configured AI model.

    Sends a tiny prompt and returns ``ok``, the model, its response, and
    latency. Use this to diagnose extraction failures seen in the review queue."""
    return _pretty(client.ai_test())


@mcp.tool()
def server_health() -> str:
    """Check that the document server is reachable and report its status,
    including the target base URL this MCP server is pointed at."""
    try:
        health = client.health()
    except APIError as exc:
        return _pretty({"reachable": False, "base_url": BASE_URL, "error": str(exc)})
    return _pretty({"reachable": True, "base_url": BASE_URL, "health": health})


def main() -> None:
    """Entry point: serve over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
