"""Python fallback for ForiFlow README screenshots.

    pip install playwright
    playwright install chromium
    python scripts/auto-capture.py
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
FRONTEND = "http://localhost:3000"
BACKEND = "http://localhost:8000"

FORM = [
    ("applicant_name", "Ali Khan"),
    ("business_name", "Khan Traders"),
    ("loan_amount_pkr", "500000"),
    ("tenure_months", "12"),
    ("monthly_digital_payments", "150000"),
    ("payment_history_score", "0.95"),
    ("inventory_turnover", "4.5"),
    ("order_consistency", "1.0"),
    ("existing_debt_pkr", "100000"),
    ("cash_flow_proxy", "1.0"),
    ("years_in_operation", "5"),
    ("num_employees", "8"),
]


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def print_start_commands() -> None:
    print()
    print("Servers are not running. Start them in two terminals, then re-run:")
    print()
    print("  Terminal 1: cd backend && python -m uvicorn main:app --reload --port 8000")
    print("  Terminal 2: cd frontend && npm run dev -- --port 3000")
    print()


def click_nav(page, label: str) -> None:
    page.get_by_role("link", name=label).first.click()
    page.wait_for_timeout(500)


def main() -> int:
    if not (http_ok(f"{BACKEND}/health") and http_ok(f"{FRONTEND}/")):
        print_start_commands()
        print("Waiting 10 seconds...")
        time.sleep(10)
        if not (http_ok(f"{BACKEND}/health") and http_ok(f"{FRONTEND}/")):
            print_start_commands()
            return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install Playwright first: pip install playwright && playwright install chromium")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1920, "height": 1080},
            color_scheme="light",
        )

        page.goto(f"{FRONTEND}/", wait_until="networkidle")
        page.get_by_text("API online").or_(page.get_by_text("Dashboard")).first.wait_for(
            timeout=20000
        )
        page.screenshot(path=str(OUT / "01-dashboard.png"), full_page=True)

        click_nav(page, "Credit Scoring")
        page.locator("#applicant_name").wait_for(timeout=15000)
        page.screenshot(path=str(OUT / "02-scoring-form.png"), full_page=True)

        for name, value in FORM:
            field = page.locator(f"#{name}")
            field.fill("")
            field.fill(value)
        page.get_by_role("button", name="Score application").click()
        page.get_by_text("Approved").or_(page.get_by_text("Rejected")).or_(
            page.get_by_text("Manual Review")
        ).first.wait_for(timeout=60000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "03-score-result.png"), full_page=True)

        button = page.get_by_role("button", name="View SHAP")
        if button.count():
            button.first.click()
        else:
            click_nav(page, "SHAP Reports")
        page.locator("svg").first.wait_for(timeout=20000)
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / "04-shap-chart.png"), full_page=True)

        click_nav(page, "EWS Alerts")
        page.locator("table, h2").first.wait_for(timeout=15000)
        page.screenshot(path=str(OUT / "05-ews-alerts.png"), full_page=True)

        click_nav(page, "Applications")
        page.locator("table tbody tr, table").first.wait_for(timeout=20000)
        page.screenshot(path=str(OUT / "06-applications.png"), full_page=True)

        page.goto(f"{BACKEND}/docs", wait_until="networkidle")
        page.locator(".swagger-ui, #swagger-ui").first.wait_for(timeout=20000)
        page.screenshot(path=str(OUT / "07-swagger.png"), full_page=True)

        browser.close()

    print("✅ Screenshots saved to docs/screenshots/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
