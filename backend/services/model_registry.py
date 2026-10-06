"""Which model scored what: the record behind ``applications.model_version``.

The first time a scoring engine is used against a database it is written to
``model_versions`` with a fingerprint of the exact files that produce its
numbers. Each application then stores the version string, the engine and the
row id, so a decision can always be traced to the model that made it, including
when the hand-weighted fallback formula was serving instead of the trained one.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.database import ModelVersion
from services import audit_service
from services.audit_service import Action
from services.scoring_service import ScoringService


def feature_set_version(features: list[str]) -> str:
    """Short fingerprint of the ordered feature list."""
    return hashlib.sha256("|".join(features).encode("utf-8")).hexdigest()[:12]


def describe(scorer: ScoringService) -> dict:
    """Everything worth recording about the engine that is scoring now."""
    metadata = getattr(scorer, "metadata", None) or {}
    features = list(getattr(scorer, "feature_names", None) or sorted(scorer.weights))
    cv = metadata.get("cross_validation", {})
    holdout = metadata.get("holdout", {})
    metrics = {
        key: value
        for key, value in {
            "cv_auc_roc_mean": cv.get("auc_roc_mean"),
            "cv_auc_roc_std": cv.get("auc_roc_std"),
            "holdout_auc_roc": holdout.get("auc"),
            "holdout_f1": holdout.get("f1"),
            "holdout_pr_auc": holdout.get("pr_auc"),
            "holdout_brier": holdout.get("brier"),
            "training_rows": metadata.get("rows"),
        }.items()
        if value is not None
    }
    return {
        "version": scorer.model_version,
        "engine": scorer.engine,
        "artifact_sha256": scorer.artifact_sha256,
        "training_dataset": metadata.get("dataset"),
        "feature_set": features,
        "feature_set_version": feature_set_version(features),
        "trained_at": metadata.get("trained_at"),
        "metrics": metrics or None,
        "fallback_reason": scorer.fallback_reason,
    }


def _find(db: Session, version: str, artifact_sha256: str) -> ModelVersion | None:
    return db.scalar(
        select(ModelVersion).where(
            ModelVersion.version == version,
            ModelVersion.artifact_sha256 == artifact_sha256,
        )
    )


def ensure_registered(
    db: Session, scorer: ScoringService, context: audit_service.AuditContext | None = None
) -> ModelVersion:
    """Return the ``model_versions`` row for ``scorer``, creating it if new.

    Also marks it the active model and retires whichever was active before.
    Flushes but does not commit: the caller's transaction carries it.
    """
    facts = describe(scorer)
    row = _find(db, facts["version"], facts["artifact_sha256"])
    if row is None:
        row = ModelVersion(**facts, status="retired")
        try:
            # A savepoint, so a second worker registering the same model at the
            # same moment loses the race without failing the caller's work.
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            row = _find(db, facts["version"], facts["artifact_sha256"])
            if row is None:  # pragma: no cover - a different constraint failed
                raise
        else:
            audit_service.record(
                db,
                action=Action.MODEL_REGISTERED,
                entity_type="model_version",
                entity_id=row.id,
                new={key: value for key, value in facts.items() if key != "feature_set"},
                details={"feature_set": facts["feature_set"]},
                context=context,
            )

    if row.status != "active" or row.fallback_reason != facts["fallback_reason"]:
        previous = db.scalars(
            select(ModelVersion.version).where(
                ModelVersion.status == "active", ModelVersion.id != row.id
            )
        ).all()
        db.execute(
            update(ModelVersion)
            .where(ModelVersion.status == "active", ModelVersion.id != row.id)
            .values(status="retired")
        )
        row.status = "active"
        row.fallback_reason = facts["fallback_reason"]
        audit_service.record(
            db,
            action=Action.MODEL_ACTIVATED,
            entity_type="model_version",
            entity_id=row.id,
            previous={"active": list(previous)},
            new={
                "active": row.version,
                "engine": row.engine,
                "fallback_reason": row.fallback_reason,
            },
            context=context,
        )
        db.flush()
    return row

