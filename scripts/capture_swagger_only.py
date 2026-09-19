"""Recapture just docs/screenshots/07-swagger.png (no login/scoring needed —
/docs is a public route). Standalone so a transient timeout on this one page
doesn't force resubmitting the scoring form again."""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "screenshots"
BACKEND = "http://127.0.0.1:8000"


def log(kind: str, message: str) -> None:
    codes = {"ok": "32", "warn": "33", "err": "31", "info": "36"}
    print(f"\033[{codes.get(kind, '0')}m[{kind.upper()}]\033[0m {message}")


def http_ok(url: str, timeout: float = 2.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main() -> int:
    from playwright.sync_api import sync_playwright

    for _ in range(10):
        if http_ok(f"{BACKEND}/health"):
            break
        log("info", "Waiting for backend...")
        time.sleep(3)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, color_scheme="light")
        page.goto(f"{BACKEND}/docs", wait_until="load", timeout=60000)
        page.locator(".swagger-ui .opblock, .swagger-ui .info").first.wait_for(timeout=45000)
        page.wait_for_timeout(1000)
        page.add_style_tag(content="[class*='sticky']{position:static !important;}")
        dest = OUT_DIR / "07-swagger.png"
        page.screenshot(path=str(dest), full_page=True)
        log("ok", str(dest))
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
