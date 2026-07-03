"""Capture the screenshots used by the in-app User Guide.

Re-run this whenever the UI changes to refresh the guide images. It drives a
headless Chromium (Playwright) against a running server and writes PNGs into
``static/images/guide/``.

Usage (from the project root, with the dev server running):
    venv/Scripts/python.exe scripts/capture_screenshots.py
    # optional: BASE_URL=http://127.0.0.1:8000 (default)

One-time setup:
    venv/Scripts/python.exe -m pip install playwright
    venv/Scripts/python.exe -m playwright install chromium
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
OUT_DIR = Path(__file__).resolve().parent.parent / "static" / "images" / "guide"
VIEWPORT = {"width": 1280, "height": 900}


def _pick_document_ids() -> tuple[str | None, str | None]:
    """Return (a complete/clean doc id, a needs-review doc id) if available."""
    complete_id = review_id = None
    try:
        docs = httpx.get(f"{BASE_URL}/api/documents", params={"page_size": 50}, timeout=15).json()
        for d in docs.get("documents", []):
            if d.get("requires_review") and review_id is None:
                review_id = d["id"]
            elif not d.get("requires_review") and complete_id is None:
                complete_id = d["id"]
        # Fall back to any document for either slot.
        any_id = docs.get("documents", [{}])[0].get("id") if docs.get("documents") else None
        complete_id = complete_id or any_id
        review_id = review_id or any_id
    except Exception as exc:  # pragma: no cover - best effort
        print(f"  (could not list documents: {exc})")
    return complete_id, review_id


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Confirm the server is up before launching a browser.
    try:
        httpx.get(f"{BASE_URL}/health", timeout=8).raise_for_status()
    except Exception as exc:
        print(f"ERROR: server not reachable at {BASE_URL} ({exc}). Start it first.")
        return 1

    complete_id, review_id = _pick_document_ids()
    print(f"Base URL: {BASE_URL}")
    print(f"Document view example: {complete_id or 'none'}")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)

        def goto(path: str) -> None:
            page.goto(f"{BASE_URL}{path}", wait_until="networkidle")
            page.wait_for_timeout(600)  # let fonts / async fetches settle

        def shot_page(path: str, name: str, full: bool = True) -> None:
            goto(path)
            page.screenshot(path=str(OUT_DIR / name), full_page=full)
            print(f"  wrote {name}")

        def shot_element(path: str, selector: str, index: int, name: str) -> None:
            goto(path)
            loc = page.locator(selector).nth(index)
            loc.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            loc.screenshot(path=str(OUT_DIR / name))
            print(f"  wrote {name}")

        # Whole pages
        shot_page("/", "dashboard.png")
        shot_page("/search", "search.png")
        shot_page("/review", "review-queue.png")
        shot_page("/settings", "settings.png")
        if complete_id:
            shot_page(f"/documents/{complete_id}", "document-view.png")

        # Focused sections on the dashboard (two `.upload-section` blocks)
        shot_element("/", ".upload-section", 0, "upload-single.png")
        shot_element("/", ".upload-section", 1, "upload-bulk.png")

        browser.close()

    print(f"Done. Images in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
