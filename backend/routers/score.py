"""Credit scoring endpoints."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.database import Application, User, get_db, utcnow
from schemas import (
    ApplicationSummary,
    Decision,
    ReviewRequest,
    ScoreResponse,
    SMEApplicant,
)
from services.auth_service import get_current_user, require_admin
from services.scoring_service import ScoringService, get_scoring_service

router = APIRouter(
    prefix="/score",
    tags=["Scoring"],
    dependencies=[Depends(get_current_user)],
)

DbSession = Annotated[Session, Depends(get_db)]
Scorer = Annotated[ScoringService, Depends(get_scoring_service)]
Officer = Annotated[User, Depends(get_current_user)]
Admin = Annotated[User, Depends(require_admin)]


@router.post(
    "",
    response_model=ScoreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Score an SME credit application",
)
async def score_application(
    applicant: SMEApplicant,
    db: DbSession,
    scorer: Scorer,
    officer: Officer,
    include_explanation: Annotated[
        bool, Query(description="Embed the SHAP explanation in the response.")
    ] = True,
) -> ScoreResponse:
    """Score an SME application, persist it and return the credit decision.

    The score runs from 0 (worst) to 100 (best) and maps onto the ForiFlow
    policy bands: 0-40 ``Rejected``, 41-70 ``Manual Review``, 71-100
    ``Approved``.
    """
    result = scorer.score(applicant)

    application = Application(
        applicant_name=applicant.applicant_name,
        business_name=applicant.business_name,
        loan_amount_pkr=applicant.loan_amount_pkr,
        tenure_months=applicant.tenure_months,
        monthly_digital_payments=applicant.monthly_digital_payments,
        payment_history_score=applicant.payment_history_score,
        inventory_turnover=applicant.inventory_turnover,
        order_consistency=applicant.order_consistency,
        existing_debt_pkr=applicant.existing_debt_pkr,
        cash_flow_proxy=applicant.cash_flow_proxy,
        years_in_operation=applicant.years_in_operation,
        num_employees=applicant.num_employees,
        risk_score=result.risk_score,
        decision=result.decision.value,
        scored_by=officer.username,
    )

    db.add(application)
    db.flush()  # assigns the primary key needed by the explanation payload

    explanation = scorer.build_explanation(
        result, application_id=application.id, business_name=application.business_name
    )
    # Persisted so the rationale can be retrieved later even if the model
    # is retrained. Not an SBP certification.
    application.shap_explanation_json = json.dumps(explanation.model_dump(mode="json"))

    db.commit()
    db.refresh(application)

    return ScoreResponse(
        application_id=application.id,
        applicant_name=application.applicant_name,
        business_name=application.business_name,
        loan_amount_pkr=application.loan_amount_pkr,
        tenure_months=application.tenure_months,
        monthly_installment_pkr=applicant.monthly_installment_pkr,
        risk_score=application.risk_score,
        decision=result.decision,
        risk_band=result.risk_band,
        confidence=result.confidence,
        model_version=scorer.model_version,
        explanation=explanation if include_explanation else None,
        created_at=application.created_at,
        scored_by=application.scored_by,
    )


@router.get(
    "/applications",
    response_model=list[ApplicationSummary],
    summary="List scored applications",
)
async def list_applications(
    db: DbSession,
    decision: Annotated[
        Decision | None, Query(description="Filter by the model's credit decision.")
    ] = None,
    pending_review: Annotated[
        bool | None,
        Query(description="true: Manual Review cases still awaiting an officer decision."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ApplicationSummary]:
    """Return scored applications, newest first, for the review dashboard."""
    statement = select(Application).order_by(Application.created_at.desc())
    if decision is not None:
        statement = statement.where(Application.decision == decision.value)
    if pending_review is True:
        statement = statement.where(
            Application.decision == Decision.MANUAL_REVIEW.value,
            Application.review_decision.is_(None),
        )
    elif pending_review is False:
        statement = statement.where(
            (Application.decision != Decision.MANUAL_REVIEW.value)
            | Application.review_decision.is_not(None)
        )

    applications = db.scalars(statement.offset(offset).limit(limit)).all()
    return [ApplicationSummary.model_validate(app) for app in applications]


@router.get(
    "/applications/{application_id}",
    response_model=ApplicationSummary,
    summary="Fetch one scored application",
)
async def get_application(application_id: int, db: DbSession) -> ApplicationSummary:
    """Return a single application or raise ``404`` if it does not exist."""
    return ApplicationSummary.model_validate(_load_application(application_id, db))


@router.post(
    "/applications/{application_id}/review",
    response_model=ApplicationSummary,
    summary="Record the officer decision on a Manual Review application (admin only)",
)
async def review_application(
    application_id: int, body: ReviewRequest, db: DbSession, officer: Admin
) -> ApplicationSummary:
    """Approve or reject a Manual Review case, with the reason, once.

    The model's band stays in ``decision``; the officer's call, note, name and
    time are stored beside it. Approved and Rejected bands are already final,
    and a recorded review cannot be overwritten.
    """
    # Row lock, so two officers deciding at once cannot both record a decision.
    application = _load_application(application_id, db, for_update=True)
    if application.decision != Decision.MANUAL_REVIEW.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Application {application.id} was {application.decision} by the model. "
                "Only Manual Review cases need an officer decision."
            ),
        )
    if application.review_decision is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Application {application.id} was already {application.review_decision} "
                f"by {application.reviewed_by}. A recorded decision is not changed."
            ),
        )

    application.review_decision = body.decision.value
    application.review_note = body.note
    application.reviewed_by = officer.username
    application.reviewed_at = utcnow()
    db.commit()
    db.refresh(application)
    return ApplicationSummary.model_validate(application)


def _load_application(
    application_id: int, db: Session, *, for_update: bool = False
) -> Application:
    """Fetch an application or raise ``404``."""
    application = db.get(Application, application_id, with_for_update=for_update)
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application {application_id} was not found.",
        )
    return application
