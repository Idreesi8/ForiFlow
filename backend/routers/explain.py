"""Explainability endpoints (SHAP-style feature attribution)."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from models.database import Application, get_db
from schemas import ExplanationResponse
from services.scoring_service import ScoringService, get_scoring_service

router = APIRouter(prefix="/explain", tags=["Explainability"])

DbSession = Annotated[Session, Depends(get_db)]
Scorer = Annotated[ScoringService, Depends(get_scoring_service)]


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
    application: Application, scorer: ScoringService
) -> ExplanationResponse:
    """Recompute the explanation from the stored applicant features."""
    result = scorer.score(application)
    return scorer.build_explanation(
        result,
        application_id=application.id,
        business_name=application.business_name,
    )


@router.post(
    "/{application_id}",
    response_model=ExplanationResponse,
    summary="Generate a SHAP explanation for an application",
)
async def explain_application(
    application_id: int,
    db: DbSession,
    scorer: Scorer,
    refresh: Annotated[
        bool,
        Query(description="Recompute the explanation instead of returning the stored one."),
    ] = False,
) -> ExplanationResponse:
    """Return the additive feature attributions behind a credit decision.

    The explanation cached at scoring time is returned unless ``refresh`` is
    set, in which case it is recomputed from the stored features and persisted
    again. Contributions are additive: their sum plus ``base_value`` equals the
    application's score.
    """
    application = _load_application(application_id, db)

    if not refresh and application.shap_explanation_json:
        try:
            return ExplanationResponse.model_validate_json(
                application.shap_explanation_json
            )
        except ValueError:
            # A schema change made the cached payload unreadable; fall through
            # and regenerate it rather than failing the request.
            pass

    explanation = _build_explanation(application, scorer)
    application.shap_explanation_json = json.dumps(explanation.model_dump(mode="json"))
    db.commit()
    return explanation


@router.get(
    "/{application_id}",
    response_model=ExplanationResponse,
    summary="Read the stored explanation for an application",
)
async def get_explanation(
    application_id: int, db: DbSession, scorer: Scorer
) -> ExplanationResponse:
    """Read-only variant used by the React dashboard's waterfall chart."""
    application = _load_application(application_id, db)

    if application.shap_explanation_json:
        try:
            return ExplanationResponse.model_validate_json(
                application.shap_explanation_json
            )
        except ValueError:
            pass

    return _build_explanation(application, scorer)
