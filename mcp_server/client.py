"""HTTP client wrapping the Related Document Server REST API.

The MCP server is a thin layer over the existing REST API. All network access
lives here so the tool layer (``server.py``) stays declarative. Every method
returns plain Python data (dicts / bytes) and raises :class:`APIError` with a
human-readable message on any transport or HTTP error, so tools can surface a
clear message to the agent instead of a stack trace.
"""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Iterator, Optional

import httpx

# Where the live Related Document Server lives. Overridable per deployment.
DEFAULT_BASE_URL = "http://192.168.88.25:8000/"
BASE_URL = os.environ.get("RDS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
# Extraction (OCR + AI) can take a while, so keep the default generous.
TIMEOUT = float(os.environ.get("RDS_TIMEOUT", "180"))


class APIError(Exception):
    """A reachable-but-failed or unreachable document server."""


class DocumentServerClient:
    """Synchronous client for the document server REST API."""

    def __init__(self, base_url: str = BASE_URL, timeout: float = TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    # -- low-level helpers -------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise APIError(
                f"Could not reach the document server at {self.base_url} "
                f"({exc.__class__.__name__}: {exc}). Check that the server is "
                f"running and RDS_BASE_URL is correct."
            ) from exc
        if resp.status_code >= 400:
            raise APIError(self._error_detail(resp))
        return resp

    @staticmethod
    def _error_detail(resp: httpx.Response) -> str:
        detail: Any
        try:
            body = resp.json()
            detail = body.get("detail", body) if isinstance(body, dict) else body
        except Exception:
            detail = resp.text[:500]
        return f"Server returned {resp.status_code}: {detail}"

    def _get_json(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, params=self._clean(params)).json()

    @staticmethod
    def _clean(params: Optional[dict]) -> dict:
        """Drop None values so we don't send empty query params."""
        if not params:
            return {}
        return {k: v for k, v in params.items() if v is not None}

    @staticmethod
    def _file_part(path: Path) -> dict:
        if not path.exists():
            raise APIError(f"File not found: {path}")
        if not path.is_file():
            raise APIError(f"Not a file: {path}")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return {"file": (path.name, path.read_bytes(), content_type)}

    # -- documents: read ---------------------------------------------------

    def list_documents(self, page: int = 1, page_size: int = 20) -> dict:
        return self._get_json(
            "/api/documents", {"page": page, "page_size": page_size}
        )

    def review_queue(self, page: int = 1, page_size: int = 20) -> dict:
        return self._get_json(
            "/api/documents/review-queue", {"page": page, "page_size": page_size}
        )

    def get_document(self, document_id: str) -> dict:
        return self._get_json(f"/api/documents/{document_id}")

    def get_preview(self, document_id: str, page: int = 1) -> bytes:
        resp = self._request(
            "GET", f"/api/documents/{document_id}/preview/{page}"
        )
        return resp.content

    def search(self, params: dict) -> dict:
        return self._get_json("/api/search", params)

    # -- documents: write --------------------------------------------------

    def upload(self, path: Path, document_type: Optional[str] = None) -> dict:
        data = {"document_type": document_type} if document_type else None
        resp = self._request(
            "POST",
            "/api/documents/upload/manual",
            files=self._file_part(path),
            data=data,
        )
        return resp.json()

    def bulk_upload(self, path: Path) -> dict:
        """Upload one file to the streaming endpoint; return the final event.

        The endpoint streams NDJSON stage events; the agent only needs the
        terminal result, so we consume the stream and return the last object
        (plus a ``stages`` trail for visibility).
        """
        stages: list[str] = []
        final: dict = {"stage": "error", "message": "no response from server"}
        try:
            with self._client.stream(
                "POST",
                "/api/documents/bulk-upload",
                files=self._file_part(path),
            ) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    raise APIError(self._error_detail(resp))
                for line in resp.iter_lines():
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    stage = event.get("stage")
                    if stage in ("identify", "ocr", "ai"):
                        stages.append(stage)
                    else:
                        final = event
        except httpx.RequestError as exc:
            raise APIError(
                f"Could not reach the document server at {self.base_url} "
                f"({exc.__class__.__name__}: {exc})."
            ) from exc
        final = dict(final)
        final["stages"] = stages
        return final

    def update_document(self, document_id: str, payload: dict) -> dict:
        resp = self._request(
            "POST", f"/api/documents/{document_id}", json=self._clean(payload)
        )
        return resp.json()

    # -- config / diagnostics ---------------------------------------------

    def document_types(self) -> Any:
        return self._get_json("/api/document-types")

    def ai_status(self) -> dict:
        return self._get_json("/api/settings/ai")

    def ai_test(self) -> dict:
        return self._request("POST", "/api/settings/ai/test").json()

    def health(self) -> dict:
        return self._get_json("/health")
