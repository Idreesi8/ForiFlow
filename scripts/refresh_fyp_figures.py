"""Regenerate the proposal architecture and Gantt PNGs (embedded in the docx)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
NAVY = (10, 37, 64)
TEAL = (15, 157, 116)
INK = (26, 40, 54)
MUTED = (91, 107, 122)
LINE = (226, 232, 238)
WHITE = (255, 255, 255)
PAPER = (244, 246, 248)
RED = (194, 59, 59)
AMBER = (210, 138, 26)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\segoeui.ttf" if not bold else r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arial.ttf" if not bold else r"C:\Windows\Fonts\arialbd.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.ImageFont, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=face) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_wrapped(draw, text, xy, face, fill, width, leading=4):
    x, y = xy
    for line in wrap(draw, text, face, width):
        draw.text((x, y), line, font=face, fill=fill)
        y += face.size + leading
    return y


def architecture() -> Path:
    w, h = 1600, 620
    img = Image.new("RGB", (w, h), PAPER)
    draw = ImageDraw.Draw(img)
    title = font(28, True)
    small = font(15)
    body = font(16)
    label = font(14, True)
    kpi = font(13)

    draw.rectangle((0, 0, w, 78), fill=NAVY)
    draw.text((36, 16), "ForiFlow — delivered prototype architecture", font=title, fill=WHITE)
    draw.text(
        (36, 50),
        "On-premise Docker  ·  FastAPI + React 18  ·  XGBoost + RF 0.60/0.40  ·  SHAP TreeExplainer  ·  PostgreSQL 16.6  ·  JWT HS256",
        font=small,
        fill=(154, 230, 201),
    )

    panels = [
        (
            "1. OFFICER INTAKE",
            "12 fields in PKR. Unused ones (tenure, inventory, order consistency, existing debt, employees) show an amber label and do not move this score. POST /api/score after JWT login.",
        ),
        (
            "2. SCORING ENGINE",
            "Maps loan_to_income, payment_history_score, years_in_operation. Ensemble PD → score = 100 × (1 − PD). Served CV AUC 0.7758 ± 0.0075, hold-out 0.7756 (public/proxy file, n=32,581). Linear surrogate only if pickles are missing.",
        ),
        (
            "3. DECISION",
            "0–40 Rejected · 41–70 Manual review · 71–100 Approved. Relative ranking after SMOTE-in-CV, not a calibrated PD. SHAP cards are rounded so they add to the displayed score.",
        ),
        (
            "4. DASHBOARD :3000",
            "Login, then Dashboard / Credit Scoring / SHAP / EWS / Applications. Bound to 127.0.0.1. Axios /api. No threshold panel, no live ECIB, not SBP-certified.",
        ),
        (
            "5. API :8000",
            "POST /auth/login. Protected /score, /explain/{id}, /ews/*. GET /health is public. nginx strips /api. Alembic 0001 + 0002_users. Volume foriflow-pgdata.",
        ),
        (
            "6. EARLY WARNING",
            "Officer types month, ageing, bureau balance, POS. Rule on the origination baseline — ensemble is not re-run. Alert if drop > 15. UI filters: All / Active / Resolved.",
        ),
    ]
    gap = 16
    left = 24
    top = 100
    pw = (w - left * 2 - gap * 5) // 6
    ph = 430
    for i, (head, text) in enumerate(panels):
        x = left + i * (pw + gap)
        draw.rounded_rectangle((x, top, x + pw, top + ph), radius=12, fill=WHITE, outline=LINE, width=2)
        draw.rounded_rectangle((x + 14, top + 16, x + 42, top + 44), radius=8, fill=TEAL)
        draw.text((x + 24, top + 20), str(i + 1), font=label, fill=WHITE)
        draw.text((x + 50, top + 20), head.split(". ", 1)[1], font=label, fill=NAVY)
        draw_wrapped(draw, text, (x + 16, top + 62), body, INK, pw - 32, leading=6)

    draw.rectangle((0, h - 52, w, h), fill=NAVY)
    draw.text(
        (36, h - 36),
        "github.com/Idreesi8/ForiFlow   ·   Everyday start: start.bat / start.ps1 (no rebuild)   ·   Dashboard http://127.0.0.1:3000   ·   Seed only if no officer exists",
        font=kpi,
        fill=(197, 208, 220),
    )
    dest = OUT / "architecture-delivered.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")
    return dest


def gantt() -> Path:
    w, h = 1600, 778
    img = Image.new("RGB", (w, h), PAPER)
    draw = ImageDraw.Draw(img)
    title = font(26, True)
    small = font(15)
    body = font(16)
    bold = font(16, True)

    draw.rectangle((0, 0, w, 88), fill=NAVY)
    draw.text((36, 18), "ForiFlow — 14-week FYP build (as delivered)", font=title, fill=WHITE)
    draw.text(
        (36, 54),
        "Historical plan that produced the running prototype. No MLflow. EWS is officer-submitted. Persistence is PostgreSQL; pytest uses in-memory SQLite.",
        font=small,
        fill=(154, 230, 201),
    )

    rows = [
        ("1", "Data preparation — credit_risk_dataset.csv + Loan_default.csv", "2w", "Zakria", 0, 2),
        ("1.1", "EDA and candidate mapping", "5d", "Zakria", 0, 1),
        ("1.2", "Feature mapping (ratios, clips)", "3d", "Zakria", 1, 1),
        ("2", "Model — XGBoost + RF, SHAP, feature_names.json", "2w", "Ramzan", 2, 2),
        ("2.1", "Three-candidate bake-off (credit_risk_shared)", "5d", "Ramzan", 2, 1),
        ("2.2", "5-fold CV + hold-out; TreeExplainer", "6d", "Ramzan", 3, 1),
        ("3", "EWS — monthly monitor, >15-point alert, resolve", "2w", "Ramzan", 4, 2),
        ("3.1", "POST /ews/monitor + PostgreSQL log", "5d", "Ramzan", 4, 1),
        ("3.2", "Alert trigger and heuristic days-to-default", "3d", "Ramzan", 5, 1),
        ("4", "Backend API — FastAPI, JWT, Alembic, Docker, Pytest", "2w", "Both", 6, 2),
        ("4.1", "/auth/login /score /explain /ews /health", "6d", "Ramzan", 6, 1),
        ("4.2", "Compose + nginx /api + 127.0.0.1 bind", "2d", "Ramzan", 7, 1),
        ("4.3", "Pytest + HTTPX (SQLite in CI)", "3d", "Zakria", 7, 1),
        ("5", "Frontend + integration — login + 5 sidebar routes", "6w", "Both", 8, 6),
        ("5.1", "React workspace (score, SHAP, EWS, applications)", "11d", "Zakria", 8, 2),
        ("5.2", "End-to-end + GitHub CI (surrogate pytest)", "10d", "Both", 10, 2),
        ("5.3", "Buffer, screenshots, start.bat demo pack", "21d", "Both", 11, 3),
    ]

    left, top = 24, 108
    table_w = w - 48
    name_w = 620
    dur_w = 70
    who_w = 90
    week_w = (table_w - name_w - dur_w - who_w - 36) / 14
    row_h = 36
    draw.rounded_rectangle((left, top, left + table_w, top + 36 + len(rows) * row_h), radius=10, fill=WHITE, outline=LINE, width=2)
    headers = [("ID", 12), ("Task", 48), ("Dur", 12 + name_w), ("Who", 12 + name_w + dur_w)]
    draw.rectangle((left, top, left + table_w, top + 36), fill=NAVY)
    draw.text((left + 12, top + 8), "ID", font=bold, fill=WHITE)
    draw.text((left + 48, top + 8), "Task", font=bold, fill=WHITE)
    draw.text((left + 12 + name_w, top + 8), "Dur", font=bold, fill=WHITE)
    draw.text((left + 12 + name_w + dur_w, top + 8), "Who", font=bold, fill=WHITE)
    for week in range(14):
        x = left + 12 + name_w + dur_w + who_w + week * week_w
        draw.text((x + 4, top + 8), str(week + 1), font=small, fill=(154, 230, 201))

    for i, (tid, task, dur, who, start, length) in enumerate(rows):
        y = top + 36 + i * row_h
        if i % 2 == 0:
            draw.rectangle((left + 1, y, left + table_w - 1, y + row_h), fill=(247, 250, 252))
        draw.text((left + 12, y + 8), tid, font=bold, fill=NAVY)
        draw.text((left + 48, y + 8), task, font=body, fill=INK)
        draw.text((left + 12 + name_w, y + 8), dur, font=body, fill=MUTED)
        draw.text((left + 12 + name_w + dur_w, y + 8), who, font=body, fill=MUTED)
        bar_x = left + 12 + name_w + dur_w + who_w + start * week_w
        bar_w = max(length * week_w - 6, 10)
        color = TEAL if length >= 2 else (18, 80, 110)
        draw.rounded_rectangle((bar_x, y + 10, bar_x + bar_w, y + 26), radius=4, fill=color)

    dest = OUT / "gantt-delivered.png"
    img.save(dest, "PNG")
    return dest


if __name__ == "__main__":
    print(architecture())
    print(gantt())
