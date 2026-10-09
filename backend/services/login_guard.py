"""Brute-force protection for ``POST /auth/login`` (2.3).

Two layers, both temporary:

1. **Per typed username, in the database.** After ``MAX_FAILED_ATTEMPTS``
   wrong passwords within ``FAILURE_WINDOW``, that username is locked for
   ``LOCKOUT_PERIOD``; every attempt is refused until then, even with the right
   password. The lock lifts by itself: an account is never locked
   permanently. Unknown usernames are tracked the same way, so a lockout does
   not reveal which usernames exist.
2. **Per client address, in memory.** At most ``IP_MAX_ATTEMPTS`` sign-in
   requests per ``IP_WINDOW`` from one address, so one machine cannot try
   many usernames. The counter lives in this process: it resets on restart
   and is not shared between workers (the Docker stack runs one).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.database import LoginAttempt, utcnow

MAX_FAILED_ATTEMPTS = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT_PERIOD = timedelta(minutes=15)

IP_MAX_ATTEMPTS = 30
IP_WINDOW_SECONDS = 300.0

# Rows older than this with no lock are forgotten when the table is touched.
_STALE_AFTER = timedelta(days=1)


def username_key(username: str) -> str:
    """The key a typed username is counted under."""
    return username.strip().lower()[:64]


def _aware(moment: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes for timezone-aware columns.
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def seconds_locked(db: Session, key: str, now: datetime | None = None) -> int | None:
    """Seconds until ``key`` may try again, or ``None`` when it is not locked."""
    now = now or utcnow()
    row = db.get(LoginAttempt, key)
    locked_until = _aware(row.locked_until) if row is not None else None
    if locked_until is None or locked_until <= now:
        return None
    return max(1, int((locked_until - now).total_seconds() + 0.999))


@dataclass(frozen=True, slots=True)
class FailureOutcome:
    failed_count: int
    locked_now: bool
    locked_until: datetime | None


def record_failure(db: Session, key: str, now: datetime | None = None) -> FailureOutcome:
    """Count one wrong password for ``key``; lock it at the threshold."""
    now = now or utcnow()
    row = db.get(LoginAttempt, key)
    if row is None:
        row = LoginAttempt(username_key=key, failed_count=0, first_failed_at=now)
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            # Another request for the same username inserted it first.
            row = db.get(LoginAttempt, key)
            if row is None:  # pragma: no cover - a different constraint failed
                raise
    first = _aware(row.first_failed_at)
    locked_until = _aware(row.locked_until)
    if first is None or now - first > FAILURE_WINDOW or (
        locked_until is not None and locked_until <= now
    ):
        # A new window: the old failures, or an expired lock, no longer count.
        row.failed_count = 0
        row.first_failed_at = now
        row.locked_until = None
    row.failed_count += 1
    locked_now = False
    if row.failed_count >= MAX_FAILED_ATTEMPTS and row.locked_until is None:
        row.locked_until = now + LOCKOUT_PERIOD
        locked_now = True
    db.flush()
    _forget_stale(db, now)
    return FailureOutcome(row.failed_count, locked_now, _aware(row.locked_until))


def record_success(db: Session, key: str) -> None:
    """A correct password clears the count for ``key``."""
    db.execute(delete(LoginAttempt).where(LoginAttempt.username_key == key))


def _forget_stale(db: Session, now: datetime) -> None:
    cutoff = now - _STALE_AFTER
    stale = db.scalars(
        select(LoginAttempt.username_key).where(
            LoginAttempt.first_failed_at < cutoff,
            (LoginAttempt.locked_until.is_(None)) | (LoginAttempt.locked_until < now),
        )
    ).all()
    if stale:
        db.execute(delete(LoginAttempt).where(LoginAttempt.username_key.in_(stale)))


class SlidingWindowLimiter:
    """At most ``limit`` events per ``window`` seconds for each key."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self._events: dict[str, deque[float]] = {}
        self._reported: dict[str, float] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> float | None:
        """Record one event. Returns ``None`` if allowed, else seconds to wait."""
        now = time.monotonic() if now is None else now
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] >= self.window:
                events.popleft()
            if len(events) >= self.limit:
                return max(1.0, self.window - (now - events[0]))
            events.append(now)
            if len(self._events) > 10_000:
                self._prune(now)
            return None

    def first_refusal(self, key: str, now: float | None = None) -> bool:
        """True once per window per key, so a flood of refusals is audited once."""
        now = time.monotonic() if now is None else now
        with self._lock:
            last = self._reported.get(key)
            if last is not None and now - last < self.window:
                return False
            self._reported[key] = now
            return True

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._events.items() if not v or now - v[-1] >= self.window]:
            del self._events[key]
        for key in [k for k, t in self._reported.items() if now - t >= self.window]:
            del self._reported[key]

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._reported.clear()


login_ip_limiter = SlidingWindowLimiter(IP_MAX_ATTEMPTS, IP_WINDOW_SECONDS)
