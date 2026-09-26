"""Capture fresh ForiFlow screenshots (authenticated) into docs/screenshots/.

This is capture.py plus one addition: a login step, since the dashboard now
requires a JWT (LoginPage.jsx / RequireAuth in App.jsx). Credentials are read
from the repo's own .env (FORIFLOW_ADMIN_USERNAME / FORIFLOW_ADMIN_PASSWORD) —
nothing is hardcoded here.

Run with the stack already up (start.bat)::

    python scripts/capture_auth2.py
"""

from __future__ import annotations

import subprocess
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


def load_dotenv(root: Path) -> dict:
    env: dict[str, str] = {}
    path = root / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def click_nav(page, label: str) -> None:
    page.get_by_role("link", name=label).first.click()
    page.wait_for_timeout(400)


# App.jsx's <header> is `sticky top-0` and ApplicationForm.jsx's result
# panel <aside> is `xl:sticky xl:top-6`, both by design for normal scrolling.
# Playwright's full_page=True screenshot works by scrolling and stitching
# viewport-sized tiles, and a `position: sticky` element gets re-painted at
# the top of every tile it is still "stuck" in — on a page taller than one
# viewport that shows up as a duplicated/ghosted header or panel baked into
# the exported PNG. It is a screenshot-capture artifact, not a rendering bug
# in the app: a person scrolling the real page never sees a duplicate. We
# neutralise it only for the capture by forcing sticky elements static right
# before each screenshot, which makes the full-page stitch paint them once,
# in normal document flow, like everything else on the page.
NEUTRALISE_STICKY_CSS = "[class*='sticky']{position:static !important;}"


def _flatten_sticky(page) -> None:
    try:
        page.add_style_tag(content=NEUTRALISE_STICKY_CSS)
    except Exception:  # noqa: BLE001 — never let this block a capture
        pass


def capture(page, filename: str, action) -> None:
    dest = OUT_DIR / filename
    try:
        action(page)
        _flatten_sticky(page)
        page.screenshot(path=str(dest), full_page=True)
        log("ok", str(dest))
        return
    except Exception as first:  # noqa: BLE001 — continue the gallery
        log("warn", f"{filename} failed ({first}). Retrying in 5s.")
        page.wait_for_timeout(5000)
        try:
            action(page)
            _flatten_sticky(page)
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

    env = load_dotenv(ROOT)
    admin_user = env.get("FORIFLOW_ADMIN_USERNAME", "admin")
    admin_password = env.get("FORIFLOW_ADMIN_PASSWORD", "")
    if not admin_password:
        raise SystemExit("FORIFLOW_ADMIN_PASSWORD is not set in .env — cannot log in to capture screenshots.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1920, "height": 1080},
            color_scheme="light",
        )

        def do_login(p):
            p.goto(f"{FRONTEND}/login", wait_until="networkidle")
            if p.locator("#username").count():
                p.locator("#username").fill(admin_user)
                p.locator("#password").fill(admin_password)
                p.get_by_role("button", name="Sign in").click()
            p.get_by_text("API online").or_(p.get_by_text("Credit Officer Workspace")).first.wait_for(
                timeout=20000
            )

        log("info", "Logging in as the officer account from .env...")
        do_login(page)
        log("ok", "Logged in.")

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
            # Wait for the "Awaiting assessment" placeholder to be gone AND a
            # decision badge to be visible, so we don't catch the SPA mid
            # route-transition (it can briefly overlay the dashboard).
            p.get_by_text("Awaiting assessment").wait_for(state="detached", timeout=60000)
            p.get_by_text("Approved").or_(p.get_by_text("Rejected")).or_(
                p.get_by_text("Manual Review")
            ).first.wait_for(timeout=60000)
            p.wait_for_load_state("networkidle")
            p.wait_for_timeout(1200)

        def shap(p):
            click_nav(p, "SHAP Reports")
            p.locator("#applicant_name, input[placeholder*='Search']").first.wait_for(timeout=15000)
            # Wait for the application list to finish loading, then pick the
            # first application so a real chart renders.
            p.get_by_text("Loading...").wait_for(state="detached", timeout=20000)
            first_app = p.locator("button, [role=button], li, tr").filter(has_text="Khan").first
            if first_app.count() == 0:
                first_app = p.locator("aside, [class*=select] button, [class*=select] li").first
            if first_app.count():
                first_app.click()
            p.locator("svg").last.wait_for(timeout=20000)
            p.get_by_text("Select an application").wait_for(state="detached", timeout=5000)
            p.wait_for_timeout(1000)

        def alerts(p):
            click_nav(p, "EWS Alerts")
            p.locator("table, h2").first.wait_for(timeout=15000)
            p.get_by_text("Loading alerts...").wait_for(state="detached", timeout=20000)
            p.wait_for_timeout(500)

        def applications(p):
            click_nav(p, "Applications")
            p.locator("table tbody tr").first.wait_for(timeout=20000)

        def swagger(p):
            p.goto(f"{BACKEND}/docs", wait_until="networkidle")
            p.locator(".swagger-ui .opblock, .swagger-ui .info").first.wait_for(timeout=30000)
            p.wait_for_timeout(800)

        # Score first, then drop the previous runs' Khan Traders rows, then
        # photograph the dashboard, so every screenshot shows the one row that
        # remains in the database.
        capture(page, "02-scoring-form.png", form)
        capture(page, "03-score-result.png", result)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "cleanup_test_applications.py")],
            check=False,
        )
        capture(page, "01-dashboard.png", dashboard)
        capture(page, "04-shap-chart.png", shap)
        capture(page, "05-ews-alerts.png", alerts)
        capture(page, "06-applications.png", applications)
        capture(page, "07-swagger.png", swagger)

        browser.close()
        log("ok", "Browser closed. Servers were left running.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
