"""Collapse the screenshot-capture script's test applications to at most one.

capture_auth2.py submits a real scoring request every run (needed to produce
the "result" screenshot), each time creating a new row in the live
`applications` table for applicant "Ali Khan", business "Khan Traders". Run
this after a capture session to delete every row matching that name pair
*except the newest one* — so repeated capture runs never pile up duplicate
demo entries, but the one row a fresh "result" screenshot actually points at
is always left in place. Matching is by applicant_name + business_name, not
by id, since the id changes every run.

Alerts / EWS rows for deleted applications (if any) cascade-delete
automatically (ForeignKey ondelete="CASCADE" in backend/models/database.py).

Run with the stack's Postgres reachable on 127.0.0.1:5432 (Docker exposes it
there per docker-compose.yml):

    python scripts/cleanup_test_applications.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep",
        type=int,
        default=1,
        choices=(0, 1),
        help="Rows to keep (default 1, the newest). --keep 0 wipes every demo row for a clean slate.",
    )
    args = parser.parse_args()

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
                "SELECT id, risk_score, decision, created_at FROM applications "
                "WHERE applicant_name = %s AND business_name = %s ORDER BY created_at DESC, id DESC",
                (TARGET_APPLICANT, TARGET_BUSINESS),
            )
            rows = cur.fetchall()
            if not rows:
                log("warn", f"No {TARGET_APPLICANT!r}/{TARGET_BUSINESS!r} rows found — nothing to do.")
                return 0

            if args.keep == 1:
                keep, drop = rows[0], rows[1:]
                log("info", f"Keeping newest: id={keep[0]} score={keep[1]} decision={keep[2]!r} created={keep[3]}")
            else:
                drop = rows
                log("info", "Clean slate: deleting every matching row.")
            if not drop:
                log("ok", "Nothing to delete.")
                return 0

            drop_ids = [r[0] for r in drop]
            for r in drop:
                print(f"  deleting id={r[0]} score={r[1]} decision={r[2]!r} created={r[3]}")

            cur.execute(
                "DELETE FROM applications WHERE id = ANY(%s) AND applicant_name = %s AND business_name = %s",
                (drop_ids, TARGET_APPLICANT, TARGET_BUSINESS),
            )
            deleted = cur.rowcount
            conn.commit()
            kept_note = f" Kept id={keep[0]}." if args.keep == 1 else " Kept none."
            log("ok", f"Deleted {deleted} row(s): id in {drop_ids}.{kept_note}")

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
