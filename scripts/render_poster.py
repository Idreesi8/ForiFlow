"""Render docs/foriflow-poster.html to docs/foriflow-poster.png.

Uses the same Playwright/Chromium install already used by the screenshot
capture scripts. Matches the poster's own @page size (594mm x 841mm, i.e.
2245 x 3179 CSS px at 96dpi) so the exported PNG matches the print layout.

Run with:
    python scripts\\render_poster.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "docs" / "foriflow-poster.html"
OUT = ROOT / "docs" / "foriflow-poster.png"

WIDTH = 2245
HEIGHT = 3179


def log(kind: str, message: str) -> None:
    codes = {"ok": "32", "warn": "33", "err": "31", "info": "36"}
    print(f"\033[{codes.get(kind, '0')}m[{kind.upper()}]\033[0m {message}")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("err", "Playwright is not installed. pip install playwright && playwright install chromium")
        return 1

    if not HTML.exists():
        log("err", f"Poster HTML not found at {HTML}")
        return 1

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, color_scheme="light")
        page.goto(HTML.as_uri(), wait_until="networkidle")
        # Let @font-face (Google Fonts) finish swapping in before we capture.
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT), full_page=True)
        browser.close()
        log("ok", f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
