"""Capture the seven ForiFlow screenshots used in the GitHub README.

Prerequisites::

    pip install playwright
    playwright install chromium

Then, with the stack already up (Docker or local servers)::

    python scripts/capture.py
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "screenshots"
FRONTEND = "http://127.0.0.1:3000"
BACKEND = "http://127.0.0.1:8000"

APPLICANT = {
    "applicant_name": "Ali Khan",
    "business_name": "Khan Traders",
    "loan_amount_pkr": "500000",
    "tenure_months": "12",
    "monthly_digital_payments": "150000",
    "payment_history_score": "95",
    "inventory_turnover": "4.5",
    "order_consistency": "100",
    "existing_debt_pkr": "100000",
    "cash_flow_proxy": "150000",
    "years_in_operation": "5",
    "num_employees": "8",
}


def log(kind: str, message: str) -> None:
    codes = {"ok": "32", "warn": "33", "err": "31", "info": "36"}
    print(f"\033[{codes.get(kind, '0')}m[{kind.upper()}]\033[0m {message}")


def http_ok(url: str, timeout: float = 2.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def wait_for_stack(seconds: int = 15) -> None:
    backend = http_ok(f"{BACKEND}/health")
    frontend = http_ok(f"{FRONTEND}/")
    if backend and frontend:
        log("ok", "Backend and frontend are already running.")
        return

    log("warn", "Stack not reachable. Start Docker Desktop or local servers, then re-run.")
    log("info", f"Waiting {seconds}s in case they are still booting...")
    time.sleep(seconds)
    for _ in range(24):
        if http_ok(f"{BACKEND}/health") and http_ok(f"{FRONTEND}/"):
            log("ok", "Both servers answered.")
            return
        time.sleep(5)
    raise SystemExit(
        "Could not reach http://127.0.0.1:8000/health and http://127.0.0.1:3000/. "
        "Start the stack with start.bat / start.ps1 and re-run."
    )


def click_nav(page, label: str) -> None:
    page.get_by_role("link", name=label).first.click()
    page.wait_for_timeout(400)


def capture(page, filename: str, action) -> None:
    dest = OUT_DIR / filename
    try:
        action(page)
        page.screenshot(path=str(dest), full_page=True)
        log("ok", str(dest))
        return
    except Exception as first:  # noqa: BLE001 — continue the gallery
        log("warn", f"{filename} failed ({first}). Retrying in 5s.")
        page.wait_for_timeout(5000)
        try:
            action(page)
            page.screenshot(path=str(dest), full_page=True)
            log("ok", str(dest))
        except Exception as second:  # noqa: BLE001
            log("err", f"{filename} skipped: {second}")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("err", "Playwright is not installed. pip install playwright && playwright install chromium")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wait_for_stack()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1920, "height": 1080},
            color_scheme="light",
        )

        def dashboard(p):
            p.goto(f"{FRONTEND}/", wait_until="networkidle")
            p.get_by_text("API online").or_(p.get_by_text("Dashboard")).first.wait_for(timeout=20000)

        def form(p):
            click_nav(p, "Credit Scoring")
            p.locator("#applicant_name").wait_for(timeout=15000)

        def result(p):
            click_nav(p, "Credit Scoring")
            p.locator("#applicant_name").wait_for(timeout=15000)
            for name, value in APPLICANT.items():
                field = p.locator(f"#{name}")
                field.fill("")
                field.fill(value)
            p.get_by_role("button", name="Score application").click()
            p.get_by_text("Approved").or_(p.get_by_text("Rejected")).or_(
                p.get_by_text("Manual Review")
            ).first.wait_for(timeout=60000)
            p.wait_for_timeout(800)

        def shap(p):
            button = p.get_by_role("button", name="View SHAP")
            if button.count():
                button.first.click()
            else:
                click_nav(p, "SHAP Reports")
            p.locator("svg").first.wait_for(timeout=20000)
            p.wait_for_timeout(600)

        def alerts(p):
            click_nav(p, "EWS Alerts")
            p.locator("table, h2").first.wait_for(timeout=15000)

        def applications(p):
            click_nav(p, "Applications")
            p.locator("table tbody tr").first.wait_for(timeout=20000)

        def swagger(p):
            p.goto(f"{BACKEND}/docs", wait_until="networkidle")
            p.locator(".swagger-ui, #swagger-ui").first.wait_for(timeout=20000)

        capture(page, "01-dashboard.png", dashboard)
        capture(page, "02-scoring-form.png", form)
        capture(page, "03-score-result.png", result)
        capture(page, "04-shap-chart.png", shap)
        capture(page, "05-ews-alerts.png", alerts)
        capture(page, "06-applications.png", applications)
        capture(page, "07-swagger.png", swagger)

        browser.close()
        log("ok", "Browser closed. Servers were left running.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
