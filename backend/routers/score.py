"""Credit scoring endpoints."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from config import manager_approval_limit_pkr
from models.database import Alert, Application, User, get_db, utcnow
from schemas import (
    AlertStatus,
    ApplicationSummary,
    Decision,
    OfficerDecision,
    PortfolioStats,
    ReviewRequest,
    ScoreBucket,
    ScoreResponse,
    SMEApplicant,
    StatementRequest,
    UserRole,
)
from services import audit_service, borrower_service, model_registry
from services.audit_service import Action, Audit
from services.auth_service import get_current_user, require_manager
from services.scoring_service import ScoringService, get_scoring_service
from services.statement_service import StatementError, parse_statement

router = APIRouter(
    prefix="/score",
    tags=["Scoring"],
    dependencies=[Depends(get_current_user)],
)

DbSession = Annotated[Session, Depends(get_db)]
Scorer = Annotated[ScoringService, Depends(get_scoring_service)]
Officer = Annotated[User, Depends(get_current_user)]
Manager = Annotated[User, Depends(require_manager)]


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
    audit: Audit,
    include_explanation: Annotated[
        bool, Query(description="Embed the SHAP explanation in the response.")
    ] = True,
) -> ScoreResponse:
    """Score an SME application, persist it and return the credit decision.

    The score runs from 0 (worst) to 100 (best) and maps onto the ForiFlow
    policy bands: 0-40 ``Rejected``, 41-70 ``Manual Review``, 71-100
    ``Approved``.

    The application is filed under a borrower: the one named by
    ``borrower_public_id``, else the one holding the given CNIC or NTN, else a
    new one opened from the application's own details. The model version and
    engine that produced the score are stored with it, and the borrower, the
    application, the score and the explanation each get an audit entry in the
    same transaction.
    """
    evidence = _turnover_evidence(applicant)
    borrower, borrower_created = borrower_service.resolve_for_application(
        db, applicant, actor=officer, context=audit
    )
    served_model = model_registry.ensure_registered(db, scorer, audit)
    result = scorer.score(applicant)

    application = Application(
        borrower_id=borrower.id,
        model_version=served_model.version,
        scoring_engine=served_model.engine,
        model_version_id=served_model.id,
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
        business_sector=applicant.business_sector.value if applicant.business_sector else None,
        contact_phone=applicant.contact_phone,
        turnover_evidence_json=json.dumps(evidence) if evidence else None,
        risk_score=result.risk_score,
        decision=result.decision.value,
        scored_by=officer.username,
    )

    db.add(application)
    db.flush()  # assigns the primary key needed by the explanation payload

    explanation = scorer.build_explanation(
        result,
        application_id=application.id,
        business_name=application.business_name,
        applicant=applicant,
    )
    # Persisted so the rationale can be retrieved later even if the model
    # is retrained. Not an SBP certification.
    application.shap_explanation_json = json.dumps(explanation.model_dump(mode="json"))

    audit_service.record(
        db,
        action=Action.APPLICATION_CREATED,
        entity_type="application",
        entity_id=application.id,
        actor=officer,
        new={
            "borrower_id": borrower.id,
            "borrower_public_id": borrower.public_id,
            "business_name": application.business_name,
            "loan_amount_pkr": application.loan_amount_pkr,
            "tenure_months": application.tenure_months,
            "monthly_digital_payments": application.monthly_digital_payments,
            "cash_flow_proxy": application.cash_flow_proxy,
            "payment_history_score": application.payment_history_score,
            "years_in_operation": application.years_in_operation,
            "existing_debt_pkr": application.existing_debt_pkr,
            "business_sector": application.business_sector,
        },
        details={
            "borrower_created": borrower_created,
            "turnover_from_statement": bool(evidence and evidence.get("matches_statement")),
        },
        context=audit,
    )
    audit_service.record(
        db,
        action=Action.APPLICATION_SCORED,
        entity_type="application",
        entity_id=application.id,
        actor=officer,
        new={
            "risk_score": result.risk_score,
            "decision": result.decision.value,
            "risk_band": result.risk_band.value,
            "probability_of_default": result.calibrated_pd,
        },
        details={
            "model_version": served_model.version,
            "scoring_engine": served_model.engine,
            "model_version_id": served_model.id,
            "artifact_sha256": served_model.artifact_sha256,
            "fallback_reason": served_model.fallback_reason,
        },
        context=audit,
    )
    audit_service.record(
        db,
        action=Action.EXPLANATION_GENERATED,
        entity_type="application",
        entity_id=application.id,
        actor=officer,
        details={
            "model_version": explanation.model_version,
            "base_value": explanation.base_value,
            "contributions": {
                item.feature: item.contribution for item in explanation.feature_contributions
            },
        },
        context=audit,
    )

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
        model_version=application.model_version,
        scoring_engine=application.scoring_engine,
        borrower_id=borrower.id,
        borrower_public_id=borrower.public_id,
        borrower_created=borrower_created,
        probability_of_default=result.calibrated_pd,
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
    final_decision: Annotated[
        OfficerDecision | None,
        Query(description="The decision that stands: the model band, or the officer's call."),
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
    if final_decision is not None:
        statement = statement.where(_final_is(final_decision.value))

    applications = db.scalars(statement.offset(offset).limit(limit)).all()
    return [ApplicationSummary.model_validate(app) for app in applications]


# Edges sit on the policy boundaries (40 and 70), so no bar mixes decisions.
SCORE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("0-20", 0.0, 20.0),
    ("20-40", 20.0, 40.0),
    ("40-55", 40.0, 55.0),
    ("55-70", 55.0, 70.0),
    ("70-85", 70.0, 85.0),
    ("85-100", 85.0, 100.0),
)


def _final_is(decision: str):
    """SQL condition: the decision that stands equals ``decision``."""
    return or_(
        Application.decision == decision,
        and_(
            Application.decision == Decision.MANUAL_REVIEW.value,
            Application.review_decision == decision,
        ),
    )


def _in_bucket(lower: float, upper: float):
    """SQL condition: score in (lower, upper], with 0 in the first bucket."""
    if lower <= 0:
        return Application.risk_score <= upper
    return and_(Application.risk_score > lower, Application.risk_score <= upper)


def _turnover_evidence(applicant: SMEApplicant) -> dict | None:
    """Re-read the attached statement and record how it relates to the figures.

    The summary is computed here, not taken from the browser, so the stored
    evidence cannot claim more than the statement shows. ``matches_statement``
    is false when the officer changed a figure after filling it from the file.
    """
    if not applicant.statement_csv:
        return None
    try:
        summary = parse_statement(applicant.statement_csv)
    except StatementError as exc:
        raise HTTPException(status_code=422, detail=f"Statement: {exc}") from None

    def close(typed: float, computed: float) -> bool:
        return abs(typed - computed) <= max(1.0, 0.01 * computed)

    return {
        **summary.as_dict(),
        "matches_statement": close(
            applicant.monthly_digital_payments, summary.suggested_monthly_digital_payments
        )
        and close(applicant.cash_flow_proxy, summary.suggested_cash_flow_proxy),
    }


@router.post("/statement", summary="Summarise a wallet or bank statement")
async def summarise_statement(body: StatementRequest) -> dict:
    """Monthly turnover from a statement CSV, to fill the application form.

    Returns the median monthly inflow and net cash flow over full calendar
    months, how much the inflows vary, and warnings to check by hand. Nothing
    is stored by this call.
    """
    try:
        return parse_statement(body.csv).as_dict()
    except StatementError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get(
    "/stats",
    response_model=PortfolioStats,
    summary="Portfolio totals for the dashboard",
)
async def portfolio_stats(db: DbSession) -> PortfolioStats:
    """Counts, exposure, score histogram and open alerts over every row."""
    approved = _final_is(Decision.APPROVED.value)
    rejected = _final_is(Decision.REJECTED.value)
    pending = and_(
        Application.decision == Decision.MANUAL_REVIEW.value,
        Application.review_decision.is_(None),
    )
    totals = db.execute(
        select(
            func.count(Application.id),
            func.count(case((pending, 1))),
            func.count(case((approved, 1))),
            func.count(case((rejected, 1))),
            func.coalesce(func.sum(case((approved, Application.loan_amount_pkr))), 0.0),
            func.avg(Application.risk_score),
            *[
                func.count(case((_in_bucket(lower, upper), 1)))
                for _label, lower, upper in SCORE_BUCKETS
            ],
        )
    ).one()
    total, pending_count, approved_count, rejected_count, exposure, average = totals[:6]
    bucket_counts = totals[6:]

    by_band = dict.fromkeys((band.value for band in Decision), 0)
    for band, count in db.execute(
        select(Application.decision, func.count()).group_by(Application.decision)
    ):
        by_band[band] = count

    open_filter = Alert.alert_status != AlertStatus.RESOLVED.value
    open_alerts, worst_drop = db.execute(
        select(func.count(Alert.id), func.max(Alert.score_drop)).where(open_filter)
    ).one()

    return PortfolioStats(
        total_applications=total,
        model_decisions=by_band,
        pending_review=pending_count,
        final_approved=approved_count,
        final_rejected=rejected_count,
        approval_rate=round(approved_count / total * 100, 2) if total else 0.0,
        approved_exposure_pkr=float(exposure),
        average_score=round(float(average), 2) if average is not None else None,
        score_histogram=[
            ScoreBucket(label=label, lower=lower, upper=upper, count=count)
            for (label, lower, upper), count in zip(SCORE_BUCKETS, bucket_counts, strict=True)
        ],
        open_alerts=open_alerts,
        worst_open_drop=float(worst_drop) if worst_drop is not None else None,
    )


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
    summary="Record the officer decision on a Manual Review application (manager or admin)",
)
async def review_application(
    application_id: int, body: ReviewRequest, db: DbSession, officer: Manager, audit: Audit
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

    # Approval authority by size. Declining needs no higher authority.
    limit = manager_approval_limit_pkr()
    if (
        body.decision is OfficerDecision.APPROVED
        and officer.role != UserRole.ADMIN.value
        and application.loan_amount_pkr > limit
    ):
        # The refusal is itself recorded, and committed before the error leaves.
        audit_service.record(
            db,
            action=Action.APPROVAL_DENIED,
            entity_type="application",
            entity_id=application.id,
            actor=officer,
            details={
                "reason": "above_manager_limit",
                "loan_amount_pkr": application.loan_amount_pkr,
                "manager_approval_limit_pkr": limit,
            },
            context=audit,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"A facility of PKR {application.loan_amount_pkr:,.0f} is above the manager "
                f"approval limit of PKR {limit:,.0f}. An admin must approve it. "
                "A manager can still reject it."
            ),
        )

    application.review_decision = body.decision.value
    application.review_note = body.note
    application.reviewed_by = officer.username
    application.reviewed_at = utcnow()
    audit_service.record(
        db,
        action=Action.OFFICER_DECISION,
        entity_type="application",
        entity_id=application.id,
        actor=officer,
        previous={"decision": application.decision, "review_decision": None},
        new={
            "review_decision": application.review_decision,
            "review_note": application.review_note,
            "reviewed_by": application.reviewed_by,
            "reviewed_at": application.reviewed_at,
        },
        details={
            "risk_score": application.risk_score,
            "loan_amount_pkr": application.loan_amount_pkr,
            "model_version": application.model_version,
        },
        context=audit,
    )
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
