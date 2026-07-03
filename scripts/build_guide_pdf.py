"""Export the in-app User Guide (/guide) to a distributable PDF.

Renders the live guide page with headless Chromium (Playwright) using print
media, so the ``@media print`` rules in style.css apply and the guide comes out
as a clean, light, paper-friendly handout. Re-run whenever the guide or its
screenshots change.

Usage (from the project root, with the dev server running):
    venv/Scripts/python.exe scripts/build_guide_pdf.py
    # optional: BASE_URL=http://127.0.0.1:8000 (default)

Output: docs/Related-Document-Server-User-Guide.pdf

One-time setup (already done if you ran capture_screenshots.py):
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
OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "Related-Document-Server-User-Guide.pdf"

HEADER = (
    '<div style="font-size:8px;width:100%;padding:0 14mm;text-align:right;'
    'color:#9aa7b2;">Related Document Server</div>'
)
FOOTER = (
    '<div style="font-size:8px;width:100%;padding:0 14mm;text-align:center;'
    'color:#66757f;">User Guide &nbsp;&middot;&nbsp; Page '
    '<span class="pageNumber"></span> of <span class="totalPages"></span></div>'
)


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        httpx.get(f"{BASE_URL}/health", timeout=8).raise_for_status()
    except Exception as exc:
        print(f"ERROR: server not reachable at {BASE_URL} ({exc}). Start it first.")
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{BASE_URL}/guide", wait_until="networkidle")
        page.wait_for_timeout(600)  # let fonts / images settle
        page.emulate_media(media="print")
        page.pdf(
            path=str(OUT_PATH),
            format="A4",
            print_background=True,
            prefer_css_page_size=False,
            display_header_footer=True,
            header_template=HEADER,
            footer_template=FOOTER,
            margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
        )
        browser.close()

    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"Wrote {OUT_PATH} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
