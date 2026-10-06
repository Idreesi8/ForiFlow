"""The append-only audit trail: who did what, to which record, and when.

Every business or security action calls :func:`record` inside the same
database transaction as the change it describes, so an action and its audit
entry are committed together or not at all. Entries are never updated or
deleted (see ``models.database.AuditLog``); a correction is another entry.

Nothing secret is written. :func:`scrub` drops any key that looks like a
credential, and a CNIC or NTN is stored masked.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from models.database import AuditLog, User

SYSTEM_ACTOR = "system"
REDACTED = "[redacted]"

# Key names whose values never belong in an audit entry.
_SECRET_KEY = re.compile(
    r"password|passwd|secret|token|authorization|api[_-]?key|credential|cookie", re.IGNORECASE
)
# A request id supplied by a proxy is kept only if it is plainly harmless.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_MAX_TEXT = 2_000


class Action:
    """Every action the trail records. ``entity.verb``, lower case."""

    LOGIN = "auth.login"
    LOGIN_FAILED = "auth.login_failed"
    USER_CREATED = "user.created"
    BORROWER_CREATED = "borrower.created"
    BORROWER_UPDATED = "borrower.updated"
    APPLICATION_CREATED = "application.created"
    APPLICATION_SCORED = "application.scored"
    EXPLANATION_GENERATED = "explanation.generated"
    EXPLANATION_RECOMPUTED = "explanation.recomputed"
    OFFICER_DECISION = "application.officer_decision"
    APPROVAL_DENIED = "application.approval_denied"
    EWS_OBSERVATION_CREATED = "ews.observation_created"
    EWS_OBSERVATION_UPDATED = "ews.observation_updated"
    EWS_ALERT_CREATED = "ews.alert_created"
    EWS_ALERT_UPDATED = "ews.alert_updated"
    EWS_ALERT_AUTO_RESOLVED = "ews.alert_auto_resolved"
    EWS_ALERT_TAKEN = "ews.alert_taken"
    EWS_ALERT_RESOLVED = "ews.alert_resolved"
    RECOMMENDATION_GENERATED = "recommendation.generated"
    APPLICATION_ESCALATED = "application.escalated"
    APPLICATION_RESCORED = "application.rescored"
    APPLICATION_SUPERSEDED = "application.superseded"
    POLICY_CREATED = "policy.created"
    POLICY_ACTIVATED = "policy.activated"
    POLICY_RETIRED = "policy.retired"
    MODEL_REGISTERED = "model.registered"
    MODEL_ACTIVATED = "model.activated"
    MIGRATION = "migration.applied"


@dataclass(frozen=True, slots=True)
class AuditContext:
    """Where a request came from, for the audit entry."""

    ip_address: str | None = None
    request_id: str | None = None


def new_request_id(supplied: str | None = None) -> str:
    """Return the caller's request id if it is safe to store, else a fresh one."""
    if supplied and _SAFE_REQUEST_ID.match(supplied):
        return supplied
    return uuid.uuid4().hex


def client_ip(request: Request) -> str | None:
    """Best available client address.

    The dashboard reaches the API through the bundled nginx, which sets
    ``X-Real-IP``; that header is believed only when the direct peer is a
    private or loopback address, which is what a proxy on the same host or
    Docker network is. It is still only as trustworthy as that network: if the
    API port is reachable by anyone other than the proxy, the header can be set
    by the caller.
    """
    import ipaddress

    peer = request.client.host if request.client else None
    if peer is None:
        return None
    forwarded = (request.headers.get("x-real-ip") or "").strip()
    try:
        behind_proxy = ipaddress.ip_address(peer).is_private or ipaddress.ip_address(peer).is_loopback
        if forwarded and behind_proxy:
            return str(ipaddress.ip_address(forwarded))
    except ValueError:
        pass
    return peer[:45]


def get_audit_context(request: Request) -> AuditContext:
    """FastAPI dependency: the caller's address and this request's id."""
    return AuditContext(
        ip_address=client_ip(request),
        request_id=getattr(request.state, "request_id", None),
    )


Audit = Annotated[AuditContext, Depends(get_audit_context)]


def scrub(value: Any) -> Any:
    """Make a value safe and JSON-ready for the trail.

    Credential-like keys are replaced, dates become ISO strings, and long text
    is cut so one entry cannot grow without limit.
    """
    if isinstance(value, dict):
        return {
            str(key): REDACTED if _SECRET_KEY.search(str(key)) else scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [scrub(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        return value if len(value) <= _MAX_TEXT else value[:_MAX_TEXT] + "…"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: int | str | None = None,
    actor: User | None = None,
    username: str | None = None,
    previous: dict | None = None,
    new: dict | None = None,
    details: dict | None = None,
    context: AuditContext | None = None,
) -> AuditLog:
    """Add one audit entry to the session. The caller commits.

    ``actor`` is the signed-in officer. Without one, ``username`` names who
    acted (the name typed on a failed login, or ``system``).
    """
    entry = AuditLog(
        user_id=actor.id if actor is not None else None,
        username=(actor.username if actor is not None else (username or SYSTEM_ACTOR))[:64],
        role=actor.role if actor is not None else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        previous_state=scrub(previous) if previous is not None else None,
        new_state=scrub(new) if new is not None else None,
        details=scrub(details) if details is not None else None,
        ip_address=context.ip_address if context is not None else None,
        request_id=context.request_id if context is not None else None,
    )
    db.add(entry)
    return entry
