"""Patch docs/ForiFlow-Proposal-Final.docx text and replace stale figures."""

from __future__ import annotations

import io
import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from xml.etree import ElementTree as ET

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DOCX = ROOT / "docs" / "ForiFlow-Proposal-Final.docx"
SHOTS = ROOT / "docs" / "screenshots"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_V23 = (
    "Version 2.3: everyday Windows start is start.bat / start.ps1 (starts Docker Desktop if needed, no rebuild); API, dashboard, and Postgres are published on 127.0.0.1 only; unused intake fields carry an amber label; SHAP summary cards are rounded so they add to the displayed score; EWS filters are All / Active / Resolved; sidebar copy is on-premise explainability (no live ECIB, not SBP-certified), not 'SBP compliance mode'; live MVP click-through verified 5 September 2026."
)

REPLACEMENTS = [
    (f"{_V23} {_V23}", _V23),
    (
        "the first officer is created with python -m scripts.seed_admin after the backend is healthy; pytest still uses in-memory SQLite.",
        "the first officer is created with python -m scripts.seed_admin after the backend is healthy; pytest still uses in-memory SQLite. Version 2.3: everyday Windows start is start.bat / start.ps1 (starts Docker Desktop if needed, no rebuild); API, dashboard, and Postgres are published on 127.0.0.1 only; unused intake fields carry an amber label; SHAP summary cards are rounded so they add to the displayed score; EWS filters are All / Active / Resolved; sidebar copy is on-premise explainability (no live ECIB, not SBP-certified), not 'SBP compliance mode'; live MVP click-through verified 5 September 2026.",
    ),
    (
        "The first officer account is created with python -m scripts.seed_admin after the backend is healthy, not automatically at startup. ForiFlow is designed to support SBP-oriented explainability; it is not SBP-certified. The dashboard label 'SBP compliance mode' is product copy, not a certification.",
        "The first officer account is created with python -m scripts.seed_admin after the backend is healthy, not automatically at startup. On Windows, start.bat (or start.ps1) starts Docker Desktop if needed, brings existing images up, and reminds the officer to seed only when no user exists. The API, dashboard, and PostgreSQL are published on 127.0.0.1 only. Unused intake fields show an amber label that they do not move this score. SHAP summary cards are rounded so a credit officer can add them to the displayed 1-decimal score. EWS filters are All, Active, and Resolved (In Review is a backend enum only). ForiFlow is designed to support SBP-oriented explainability; it is not SBP-certified. The sidebar states that there is no live ECIB feed.",
    ),
    (
        "The first officer is seeded with docker compose exec backend python -m scripts.seed_admin (password from FORIFLOW_ADMIN_PASSWORD; --reset-password rotates an existing hash). Pytest uses in-memory SQLite so the suite does not need a live database.",
        "The first officer is seeded with docker compose exec backend python -m scripts.seed_admin (password from FORIFLOW_ADMIN_PASSWORD; --reset-password rotates an existing hash). Everyday start on this laptop is start.bat / start.ps1 (127.0.0.1 bind, no rebuild). Pytest uses in-memory SQLite so the suite does not need a live database.",
    ),
    (
        "application list with per-decision SHAP retrieval. Met in the running prototype. Risk bands are code constants, not a live Threshold Configuration panel.",
        "application list with per-decision SHAP retrieval. Unused intake fields show an amber 'not currently used in this risk score' label. SHAP summary cards add to the displayed score. EWS filters are All / Active / Resolved. Met in the running prototype. Risk bands are code constants, not a live Threshold Configuration panel.",
    ),
    (
        "Inventory turnover, order consistency, headcount, existing debt, and tenure are persisted but do not move the present ML score.",
        "Inventory turnover, order consistency, headcount, existing debt, and tenure are persisted but do not move the present ML score; each of those fields shows an amber label on the intake form.",
    ),
    (
        "Stored SHAP payloads support audit retrieval. The prototype is designed to support SBP-oriented explainability; it is not an SBP certification.",
        "The on-screen summary cards (base, positive, negative, final) are rounded so they add to the displayed score. Stored SHAP payloads support audit retrieval. The prototype is designed to support SBP-oriented explainability; it is not an SBP certification.",
    ),
    (
        "The API returns alerts worst-first. Clicking through can open the related SHAP report; it does not load a Month 1",
        "The feed filters client-side as All / Active / Resolved (In Review is not shown). Resolve updates the queue without a refresh. The API returns alerts worst-first. Clicking through can open the related SHAP report; it does not load a Month 1",
    ),
    (
        "There is no notification bell, model-version selector, or System settings page. Docker nginx (or Vite in development) proxies /api to FastAPI.",
        "There is no notification bell, model-version selector, or System settings page. The sidebar states on-premise explainability, officer-typed bureau fields, and that ForiFlow is not SBP-certified. Docker nginx (or Vite in development) proxies /api to FastAPI. Ports are published on 127.0.0.1 only.",
    ),
    (
        "Bank IT (intended): copies .env.example to .env, sets POSTGRES_* and JWT_SECRET_KEY, runs docker compose up, then seeds the admin user. This FYP ships Docker Compose on a laptop; Postgres is bound to loopback only.",
        "Bank IT (intended): copies .env.example to .env, sets POSTGRES_* and JWT_SECRET_KEY, double-clicks start.bat (or runs start.ps1), then seeds the admin user only if start.ps1 reports none. This FYP ships Docker Compose on a laptop; Postgres, the API, and the dashboard are bound to 127.0.0.1 only.",
    ),
    (
        "Versions 2.0-2.2 rewrote the body to match the implemented repository, measured AUCs, PostgreSQL, and JWT login.",
        "Versions 2.0-2.3 rewrote the body to match the implemented repository, measured AUCs, PostgreSQL, JWT login, start.bat, and the live officer UI.",
    ),
    (
        "The live app requires JWT login (unauthenticated browsers go to /login). There is no notification bell. Screenshots in this section were captured of the officer workspace after the API is online.",
        "The live app requires JWT login (unauthenticated browsers go to /login). The sidebar reads on-premise explainability, not SBP compliance mode. There is no notification bell. Screenshots in this section were recaptured from the officer workspace after the API is online.",
    ),
    (
        "a structured form with numeric validation and a",
        "a structured form with numeric validation, amber unused-field labels, and a",
    ),
    (
        "The trigger is a derived-score drop greater than 15 points. Estimated days-to-default is a heuristic. The monthly score is rule-based, not a second XGBoost pass.",
        "The trigger is a derived-score drop greater than 15 points. Filters are All / Active / Resolved. Estimated days-to-default is a heuristic. The monthly score is rule-based, not a second XGBoost pass.",
    ),
    (
        "React dashboard on port 3000 proxies /api to FastAPI on port 8000. PostgreSQL is bound to 127.0.0.1:5432.",
        "React dashboard on 127.0.0.1:3000 proxies /api to FastAPI on 127.0.0.1:8000. Everyday start is start.bat / start.ps1. PostgreSQL is bound to 127.0.0.1:5432.",
    ),
]


def replace_in_paragraph(paragraph, old: str, new: str) -> bool:
    texts = paragraph.findall(f".//{W}t")
    if not texts:
        return False
    joined = "".join(t.text or "" for t in texts)
    if old not in joined:
        return False
    updated = joined.replace(old, new)
    texts[0].text = updated
    for extra in texts[1:]:
        extra.text = ""
    return True


def fit_png(src: Path, max_width: int) -> bytes:
    image = Image.open(src).convert("RGB")
    if image.width > max_width:
        height = int(image.height * (max_width / image.width))
        image = image.resize((max_width, height), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def main() -> None:
    if not DOCX.exists():
        raise SystemExit(f"Missing {DOCX}")

    image_map = {
        "word/media/image2.png": SHOTS / "architecture-delivered.png",
        "word/media/image3.png": SHOTS / "gantt-delivered.png",
        "word/media/image4.png": SHOTS / "01-dashboard.png",
        "word/media/image5.png": SHOTS / "02-scoring-form.png",
        "word/media/image6.png": SHOTS / "04-shap-chart.png",
        "word/media/image7.png": SHOTS / "05-ews-alerts.png",
    }

    tmp = Path(tempfile.mkdtemp(prefix="foriflow-docx-"))
    try:
        with ZipFile(DOCX) as zin:
            zin.extractall(tmp)

        doc_path = tmp / "word" / "document.xml"
        tree = ET.parse(str(doc_path))
        root = tree.getroot()
        hits = 0
        for paragraph in root.iter(f"{W}p"):
            for old, new in REPLACEMENTS:
                if replace_in_paragraph(paragraph, old, new):
                    hits += 1
            texts = paragraph.findall(f".//{W}t")
            joined = "".join(t.text or "" for t in texts)
            if joined.startswith("Revision history") and joined.count(_V23) > 1:
                texts[0].text = joined.split(_V23)[0] + _V23
                for extra in texts[1:]:
                    extra.text = ""
                hits += 1
        # Tools table still says "3.x" in its own cell.
        for paragraph in root.iter(f"{W}p"):
            texts = paragraph.findall(f".//{W}t")
            joined = "".join(t.text or "" for t in texts)
            if joined.strip() == "3.x":
                texts[0].text = "16.6"
                for extra in texts[1:]:
                    extra.text = ""
                hits += 1
        tree.write(str(doc_path), xml_declaration=True, encoding="UTF-8")

        for dest_name, src in image_map.items():
            if src.exists():
                (tmp / dest_name).write_bytes(fit_png(src, 1600))

        backup = DOCX.with_suffix(".docx.bak")
        shutil.copy2(DOCX, backup)
        out = DOCX.with_suffix(".docx.new")
        with ZipFile(out, "w", compression=ZIP_DEFLATED) as zout:
            for path in tmp.rglob("*"):
                if path.is_file():
                    zout.write(path, path.relative_to(tmp).as_posix())
        out.replace(DOCX)
        backup.unlink(missing_ok=True)
        print(f"patched {hits} paragraphs in {DOCX}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
