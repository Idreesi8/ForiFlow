"""Create the first officer account. Password comes from the environment.

    FORIFLOW_ADMIN_PASSWORD=... python -m scripts.seed_admin

Optional: ``FORIFLOW_ADMIN_USERNAME`` (default ``admin``),
``FORIFLOW_ADMIN_ROLE`` (default ``admin``). Pass ``--reset-password`` to
replace the hash of an existing user. Never logs the password.
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import select

from models.database import SessionLocal, User, init_db
from services.auth_service import ALLOWED_ROLES, hash_password


def seed_admin(
    *,
    username: str,
    password: str,
    role: str,
    reset_password: bool = False,
) -> str:
    """Insert the user if missing. Returns ``created``, ``exists``, or ``updated``."""
    if not password:
        raise ValueError("FORIFLOW_ADMIN_PASSWORD is empty.")
    if role not in ALLOWED_ROLES:
        raise ValueError(f"Role must be one of {sorted(ALLOWED_ROLES)}.")
    username = username.strip()
    if not username:
        raise ValueError("Username is empty.")

    init_db()
    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.username == username))
        if existing is not None:
            if not reset_password:
                return "exists"
            existing.hashed_password = hash_password(password)
            if role in ALLOWED_ROLES:
                existing.role = role
            db.commit()
            return "updated"
        db.add(
            User(
                username=username,
                hashed_password=hash_password(password),
                role=role,
            )
        )
        db.commit()
        return "created"
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--username",
        default=os.getenv("FORIFLOW_ADMIN_USERNAME", "admin"),
        help="Officer username (default: FORIFLOW_ADMIN_USERNAME or admin).",
    )
    parser.add_argument(
        "--role",
        default=os.getenv("FORIFLOW_ADMIN_ROLE", "admin"),
        help="admin or analyst (default: FORIFLOW_ADMIN_ROLE or admin).",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Replace the password hash if the username already exists.",
    )
    args = parser.parse_args(argv)
    password = os.getenv("FORIFLOW_ADMIN_PASSWORD", "")
    if not password:
        print(
            "MIGRATION STOPPED: set FORIFLOW_ADMIN_PASSWORD in the environment. "
            "The password is not accepted as a CLI flag.",
            file=sys.stderr,
        )
        return 1
    try:
        outcome = seed_admin(
            username=args.username,
            password=password,
            role=args.role,
            reset_password=args.reset_password,
        )
    except ValueError as exc:
        print(f"SEED STOPPED: {exc}", file=sys.stderr)
        return 1
    if outcome == "exists":
        print(f"User {args.username!r} already exists; password unchanged.")
    elif outcome == "updated":
        print(f"Updated password for {args.role} user {args.username!r}.")
    else:
        print(f"Created {args.role} user {args.username!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
