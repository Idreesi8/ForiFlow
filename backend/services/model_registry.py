"""Which model scored what: the record behind ``applications.model_version``.

The first time a scoring engine is used against a database it is written to
``model_versions`` with a fingerprint of the exact files that produce its
numbers. Each application then stores the version string, the engine and the
row id, so a decision can always be traced to the model that made it, including
when the hand-weighted fallback formula was serving instead of the trained one.
"""

from __future__ import annotations

import hashlib
import math

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


def _json_safe(value):
    """``value`` with NaN and infinities spelled as strings.

    PostgreSQL JSONB rejects the bare ``NaN`` token that Python's ``json``
    writes (XGBoost's ``missing`` parameter is NaN), so registration failed on
    PostgreSQL. The setting is kept, as the text ``"NaN"``, not dropped.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def describe(scorer: ScoringService) -> dict:
    """Everything worth recording about the engine that is scoring now."""
    metadata = getattr(scorer, "metadata", None) or {}
    evaluation = getattr(scorer, "evaluation", None) or {}
    features = list(getattr(scorer, "feature_names", None) or sorted(scorer.weights))
    cv = metadata.get("cross_validation", {})
    holdout = metadata.get("holdout", {})
    validation = (metadata.get("validation") or {}).get("ensemble_raw") or {}
    final_test = (evaluation.get("final_test") or {}).get("metrics_raw") or {}
    final_calibrated = (evaluation.get("final_test") or {}).get("metrics_calibrated") or {}
    metrics = {
        key: value
        for key, value in {
            "cv_auc_roc_mean": cv.get("auc_roc_mean"),
            "cv_auc_roc_std": cv.get("auc_roc_std"),
            # Pre-2.2 artefacts only: the reused 20% hold-out.
            "holdout_auc_roc": holdout.get("auc"),
            "holdout_f1": holdout.get("f1"),
            "holdout_pr_auc": holdout.get("pr_auc"),
            "holdout_brier": holdout.get("brier"),
            "validation_auc_roc": validation.get("auc_roc"),
            "final_test_auc_roc": final_test.get("auc_roc"),
            "final_test_pr_auc": final_test.get("pr_auc"),
            "final_test_precision": final_test.get("precision"),
            "final_test_recall": final_test.get("recall"),
            "final_test_f1": final_test.get("f1"),
            "final_test_brier_raw": final_test.get("brier"),
            "final_test_brier_calibrated": final_calibrated.get("brier"),
            "training_rows": metadata.get("rows"),
        }.items()
        if value is not None
    }
    calibration = metadata.get("calibration") or {}
    provenance = (
        {
            "dataset_identifier": metadata.get("dataset_identifier"),
            "dataset_type": metadata.get("dataset_type_label"),
            "dataset_sha256": metadata.get("dataset_sha256"),
            "random_seed": metadata.get("random_seed"),
            "split": {
                key: (metadata.get("split") or {}).get(key)
                for key in ("method", "seed", "rows", "id_sha256")
            },
            "preprocessing_version": (metadata.get("preprocessing") or {}).get("version"),
            "calibration_method": calibration.get("method_label"),
            "training_protocol_version": metadata.get("training_protocol_version"),
            "model_config": metadata.get("model_config"),
        }
        if metadata.get("training_protocol_version")
        else None
    )
    return {
        "version": scorer.model_version,
        "engine": scorer.engine,
        "artifact_sha256": scorer.artifact_sha256,
        "training_dataset": metadata.get("dataset"),
        "feature_set": features,
        "feature_set_version": feature_set_version(features),
        "trained_at": metadata.get("trained_at"),
        "metrics": _json_safe(metrics) or None,
        "provenance": _json_safe(provenance),
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

