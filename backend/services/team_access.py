"""Serialise access changes and recheck the actor inside the transaction."""
from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session
from models.database import User

# One transaction-scoped lock shared by status and role writes. This prevents
# two admins from concurrently removing each other's administrative access.
TEAM_ACCESS_LOCK = 467921089


def lock_team_change(db: Session, actor_id: int) -> User:
    return lock_officer_change(db, actor_id, frozenset({'admin'}))


def lock_officer_change(db: Session, actor_id: int, allowed_roles: frozenset[str]) -> User:
    """Share the access-change lock so authority cannot change during a protected write."""
    dialect = db.get_bind().dialect.name
    if dialect == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': TEAM_ACCESS_LOCK})
    elif dialect == 'sqlite':
        # Acquire SQLite's write reservation before reading mutable authority.
        # No value changes; the audit entry belongs only to the actual action.
        db.execute(update(User).where(User.id == actor_id).values(role=User.role),
                   execution_options={'synchronize_session': False})
    else:
        raise HTTPException(503, 'Account changes are unsupported on this database.')
    actor = db.scalar(select(User).where(User.id == actor_id).execution_options(populate_existing=True))
    if actor is None or not actor.is_active or actor.role not in allowed_roles:
        roles = ' or '.join(sorted(allowed_roles))
        raise HTTPException(403, f'Your account no longer has enabled {roles} access. Refresh your session.')
    return actor
