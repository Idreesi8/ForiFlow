"""Model evaluation endpoints: how the served model performs, and against what."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.database import Application, ModelVersion, get_db
from schemas import ModelVersionResponse
from services.auth_service import get_current_user
from services.drift_service import drift_report

router = APIRouter(
    prefix="/model",
    tags=["Model"],
    dependencies=[Depends(get_current_user)],
)


def _require(payload: dict[str, Any] | None, command: str) -> dict[str, Any]:
    """Return the recorded results or a ``404`` naming the script that makes them."""
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Not recorded yet. Run `python -m ml.{command}` in the backend.",
        )
    return payload


@router.get(
    "/versions",
    response_model=list[ModelVersionResponse],
    summary="Every model that has scored here, and which is active",
)
async def model_versions(db: Annotated[Session, Depends(get_db)]) -> list[ModelVersionResponse]:
    """Model records, newest first, with how many applications each scored.

    A model is recorded the first time it scores against this database, with a
    SHA-256 of its artefact files. ``engine`` is ``ml`` for the trained
    ensemble and ``surrogate`` for the hand-weighted fallback formula; a
    surrogate row carries the reason it was serving. Applications scored before
    this record existed keep the version string they stored and are not counted
    against a row.
    """
    counts = dict(
        db.execute(
            select(Application.model_version_id, func.count())
            .where(Application.model_version_id.is_not(None))
            .group_by(Application.model_version_id)
        ).all()
    )
    rows = db.scalars(select(ModelVersion).order_by(ModelVersion.id.desc())).all()
    return [
        ModelVersionResponse.model_validate(row).model_copy(
            update={"applications_scored": int(counts.get(row.id, 0))}
        )
        for row in rows
    ]


@router.get(
    "/versions/active",
    response_model=ModelVersionResponse,
    summary="The model scoring right now",
)
async def active_model_version(db: Annotated[Session, Depends(get_db)]) -> ModelVersionResponse:
    """The active model record; ``404`` before anything has been scored or registered."""
    row = db.scalar(select(ModelVersion).where(ModelVersion.status == "active"))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No model has been registered yet. It is recorded at startup or first score.",
        )
    count = db.scalar(
        select(func.count()).select_from(Application).where(Application.model_version_id == row.id)
    )
    return ModelVersionResponse.model_validate(row).model_copy(
        update={"applications_scored": int(count or 0)}
    )


@router.get("/evaluation", summary="Hold-out evaluation of the served model")
async def model_evaluation() -> dict[str, Any]:
    """ROC curve, class-wise results, calibration and default rate per band.

    Measured by ``ml.evaluate_model`` on the 20% hold-out that neither the
    served model nor its calibrator has seen. These figures describe the trained
    ensemble on the public training file; they are not live portfolio results.
    """
    from ml.features import load_model_evaluation

    return _require(load_model_evaluation(), "evaluate_model")


@router.get("/early-warning", summary="The fitted early-warning Markov chain")
async def early_warning_model() -> dict[str, Any]:
    """Transition matrix, outlook per state, hold-out check and alternatives.

    Fitted by ``ml.ews_markov`` on the UCI credit card file: monthly repayment
    histories of consumer card accounts in Taiwan, not SME loans.
    """
    from ml.features import load_ews_transition

    return _require(load_ews_transition(), "ews_markov")


@router.get("/drift", summary="Live applications against the training population")
async def population_drift(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Population Stability Index of the score and of each model input.

    Compares every stored application with the distributions recorded by
    ``ml.evaluate_model``. Inputs are rebuilt exactly as scoring builds them
    (same turnover estimate, clip bounds and repayment-history reading). The
    reference is the public training file, so a shift here is expected for a
    real Pakistani portfolio; it says the model needs re-validating, not that
    the applicants are worse.
    """
    from ml.features import (
        apply_clips,
        build_raw_features,
        load_feature_metadata,
        load_model_evaluation,
        payment_history_levels,
        snap_payment_history,
    )

    evaluation = _require(load_model_evaluation(), "evaluate_model")
    reference = evaluation.get("reference_distributions")
    if not reference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No reference distributions. Re-run `python -m ml.evaluate_model`.",
        )
    metadata = load_feature_metadata()
    clips = metadata.get("feature_clips", {})
    levels = payment_history_levels(metadata)

    live: dict[str, list[float]] = {name: [] for name in reference}
    for application in db.scalars(select(Application)):
        raw = build_raw_features(application)
        clipped = apply_clips(raw, clips)
        if levels is not None:
            clipped["payment_history_score"] = snap_payment_history(
                raw["payment_history_score"], levels
            )
        for name in reference:
            live[name].append(
                float(application.risk_score) if name == "risk_score" else clipped[name]
            )
    return drift_report(reference, live)


@router.get("/fairness", summary="How the model treats groups it cannot see")
async def fairness_audit() -> dict[str, Any]:
    """Approval rate, pricing gap and wrong decisions per group on the hold-out.

    Recorded by ``ml.fairness_audit`` for age, income, housing and loan purpose:
    attributes of the public file that the model never reads. The file has no
    gender, so gender is not audited.
    """
    from ml.features import load_fairness_audit

    return _require(load_fairness_audit(), "fairness_audit")


@router.get("/comparison", summary="Served model against the alternatives")
async def model_comparison() -> dict[str, Any]:
    """Cross-validated metrics of every model the ensemble was chosen over.

    Recorded by ``ml.compare_models`` with the same data, folds and pipeline
    for each model, including a paired t-test against the served ensemble.
    """
    from ml.features import load_model_comparison

    return _require(load_model_comparison(), "compare_models")
