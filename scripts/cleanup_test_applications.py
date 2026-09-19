"""Delete the two test applications the screenshot-capture script created.

capture_auth.py / capture_auth2.py submit a real scoring request each run
(needed to produce the "result" screenshot). That created two rows in the
live `applications` table: id 38 and id 39, both applicant "Ali Khan",
business "Khan Traders". This script removes exactly those two rows and
nothing else — the WHERE clause matches on id AND applicant_name AND
business_name together, so it refuses to touch any row that doesn't match
all three, even if ids were reused by something else in the meantime.

Alerts / EWS rows for those two applications (if any) cascade-delete
automatically (ForeignKey ondelete="CASCADE" in backend/models/database.py).

Run with the stack's Postgres reachable on 127.0.0.1:5432 (Docker exposes it
there per docker-compose.yml):

    python scripts/cleanup_test_applications.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TARGET_IDS = (38, 39)
TARGET_APPLICANT = "Ali Khan"
TARGET_BUSINESS = "Khan Traders"


def log(kind: str, message: str) -> None:
    codes = {"ok": "32", "warn": "33", "err": "31", "info": "36"}
    print(f"\033[{codes.get(kind, '0')}m[{kind.upper()}]\033[0m {message}")


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


def main() -> int:
    try:
        import psycopg2
    except ImportError:
        log("err", "psycopg2 is not installed. pip install psycopg2-binary")
        return 1

    env = load_dotenv(ROOT)
    user = env.get("POSTGRES_USER", "foriflow")
    password = env.get("POSTGRES_PASSWORD", "")
    db = env.get("POSTGRES_DB", "foriflow")
    host = env.get("POSTGRES_HOST", "127.0.0.1")
    port = env.get("POSTGRES_PORT", "5432")
    if not password:
        raise SystemExit("POSTGRES_PASSWORD is not set in .env — cannot connect.")

    conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=db)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, applicant_name, business_name, risk_score, decision, created_at "
                "FROM applications WHERE id = ANY(%s) ORDER BY id",
                (list(TARGET_IDS),),
            )
            rows = cur.fetchall()
            if not rows:
                log("warn", f"No rows found with id in {TARGET_IDS} — nothing to delete.")
                return 0

            log("info", "Rows found before delete:")
            for r in rows:
                print(f"  id={r[0]} applicant={r[1]!r} business={r[2]!r} score={r[3]} decision={r[4]!r} created={r[5]}")

            mismatched = [r for r in rows if r[1] != TARGET_APPLICANT or r[2] != TARGET_BUSINESS]
            if mismatched:
                log(
                    "err",
                    f"Refusing to delete: {len(mismatched)} row(s) with id in {TARGET_IDS} do not match "
                    f"applicant={TARGET_APPLICANT!r} business={TARGET_BUSINESS!r}. Aborting, nothing changed.",
                )
                conn.rollback()
                return 1

            cur.execute(
                "DELETE FROM applications WHERE id = ANY(%s) AND applicant_name = %s AND business_name = %s",
                (list(TARGET_IDS), TARGET_APPLICANT, TARGET_BUSINESS),
            )
            deleted = cur.rowcount
            conn.commit()
            log("ok", f"Deleted {deleted} row(s): id in {TARGET_IDS}.")

            cur.execute("SELECT COUNT(*) FROM applications")
            (total,) = cur.fetchone()
            log("ok", f"Applications table now has {total} row(s) total.")
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        log("err", f"Failed, rolled back: {exc}")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
