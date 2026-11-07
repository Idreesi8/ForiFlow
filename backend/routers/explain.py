"""Explainability endpoints (SHAP-style feature attribution)."""

from __future__ import annotations

import json
import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from models.database import Application, ModelVersion, User, get_db
from schemas import ExplanationResponse
from services import audit_service
from services.policy_rules import ScoreBands
from services.audit_service import Action, Audit
from services.auth_service import get_current_user
from services.scoring_service import ScoringService, get_scoring_service

router = APIRouter(
    prefix="/explain",
    tags=["Explainability"],
    dependencies=[Depends(get_current_user)],
)

DbSession = Annotated[Session, Depends(get_db)]
Scorer = Annotated[ScoringService, Depends(get_scoring_service)]
Officer = Annotated[User, Depends(get_current_user)]


def _load_application(application_id: int, db: Session) -> Application:
    """Fetch an application or raise a ``404`` with a readable message."""
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application {application_id} was not found.",
        )
    return application


def _build_explanation(
    application: Application, scorer: ScoringService, db: Session
) -> ExplanationResponse:
    """Recompute the explanation from the stored applicant features.

    The score is read against the cut-offs the application was assessed under,
    so a later policy change does not relabel it.
    """
    # A matching name alone is insufficient: the same label can identify
    # different model files (or changed surrogate weights).
    source = db.get(ModelVersion, application.model_version_id) if application.model_version_id else None
    if not (
        source is not None
        and source.version == application.model_version == scorer.model_version
        and source.engine == application.scoring_engine == scorer.engine
        and source.artifact_sha256 == scorer.artifact_sha256
    ):
        raise HTTPException(status_code=409, detail=(
            "The original model cannot be verified against the serving model. "
            "Its historical explanation cannot be regenerated. Read the saved "
            "explanation without refresh, or restore the original verified model. "
            "The assessment has not been changed."
        ))

    # Do not silently use today's policy when the assessment's snapshot is absent.
    try:
        snapshot = application.policy_evaluation["bands"]
        bands = ScoreBands(
            decline_max_score=float(snapshot["decline_max_score"]),
            manual_review_max_score=float(snapshot["manual_review_max_score"]),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=409, detail=(
            "The original policy thresholds are unavailable or invalid. "
            "The historical explanation cannot be regenerated using today's policy. "
            "The assessment has not been changed."
        )) from None

    result = scorer.score(application, bands)
    explanation = scorer.build_explanation(
        result,
        application_id=application.id,
        business_name=application.business_name,
        applicant=application,
        policy_version=application.policy_version,
    )
    values = [explanation.base_value, explanation.risk_score,
              *[item.contribution for item in explanation.feature_contributions]]
    # Allow only accumulated rounding to hundredths, never hide a material
    # attribution residual in the chart's display rounding.
    rounding_tolerance = 0.005 * (len(explanation.feature_contributions) + 2) + 1e-8
    if not (
        all(math.isfinite(value) for value in values)
        and math.isfinite(application.risk_score)
        and abs(explanation.risk_score - application.risk_score) <= 0.011
        and explanation.decision == application.decision
        and (application.risk_band is None or explanation.risk_band == application.risk_band)
        and abs(explanation.base_value + sum(item.contribution for item in explanation.feature_contributions)
                - explanation.risk_score) <= rounding_tolerance
    ):
        raise HTTPException(status_code=409, detail=(
            "The original assessment could not be reproduced consistently. "
            "A new explanation would be misleading, so it has not been returned or saved. "
            "Review the saved assessment and original model with an administrator."
        ))
    return explanation


def _with_reason_codes(explanation: ExplanationResponse) -> ExplanationResponse:
    """Fill in what an explanation stored before 2.0 does not carry.

    Reason codes and the recommendation wording are pure functions of what is
    already stored, so they are derived on read; the stored record is untouched.
    """
    from schemas import RECOMMENDATION_OF
    from services.reason_codes import reason_codes_for

    update: dict = {}
    if not explanation.reason_codes:
        update["reason_codes"] = reason_codes_for(explanation.feature_contributions)
    if explanation.recommendation is None:
        update["recommendation"] = RECOMMENDATION_OF[explanation.decision]
    return explanation.model_copy(update=update) if update else explanation


@router.post(
    "/{application_id}",
    response_model=ExplanationResponse,
    summary="Generate a SHAP explanation for an application",
)
async def explain_application(
    application_id: int,
    db: DbSession,
    scorer: Scorer,
    officer: Officer,
    audit: Audit,
    refresh: Annotated[
        bool,
        Query(description="Recompute the explanation instead of returning the stored one."),
    ] = False,
) -> ExplanationResponse:
    """Return the additive feature attributions behind a credit decision.

    The explanation stored at scoring time is returned unless ``refresh`` is
    set, in which case it is recomputed from the stored features with the
    original verified model and policy. The stored explanation is the audit record of why the
    decision was made, so a refresh never overwrites it; it is only written
    when none is stored or the stored one can no longer be read, and only if
    the original assessment is reproducible. Otherwise this returns 409.
    Contributions are additive: their sum plus ``base_value`` equals the score.
    """
    application = _load_application(application_id, db)

    stored: ExplanationResponse | None = None
    if application.shap_explanation_json:
        try:
            stored = ExplanationResponse.model_validate_json(
                application.shap_explanation_json
            )
        except ValueError:
            # A schema change made the stored payload unreadable; regenerate
            # it rather than failing the request.
            stored = None

    if stored is not None and not refresh:
        return _with_reason_codes(stored)

    explanation = _build_explanation(application, scorer, db)
    if stored is None:
        application.shap_explanation_json = json.dumps(
            explanation.model_dump(mode="json")
        )
    # Successful regeneration has verified the original model and score.
    audit_service.record(
        db,
        action=Action.EXPLANATION_GENERATED if stored is None else Action.EXPLANATION_RECOMPUTED,
        entity_type="application",
        entity_id=application.id,
        actor=officer,
        details={
            "scored_with": application.model_version,
            "explained_with": explanation.model_version,
            "stored": stored is None,
            "risk_score_on_file": application.risk_score,
            "risk_score_recomputed": explanation.risk_score,
        },
        context=audit,
    )
    db.commit()
    return explanation


@router.get(
    "/{application_id}",
    response_model=ExplanationResponse,
    summary="Read the stored explanation for an application",
)
async def get_explanation(
    application_id: int, db: DbSession, scorer: Scorer
) -> ExplanationResponse:  # a read: nothing is stored, so nothing is audited
    """Read-only variant used by the React dashboard's waterfall chart."""
    application = _load_application(application_id, db)

    if application.shap_explanation_json:
        try:
            return _with_reason_codes(
                ExplanationResponse.model_validate_json(application.shap_explanation_json)
            )
        except ValueError:
            pass

    return _build_explanation(application, scorer, db)
