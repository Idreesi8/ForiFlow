"""Credit scoring endpoints."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from models.database import ALERT_OPEN_STATUSES, Alert, Application, User, get_db, utcnow
from schemas import (
    ApplicationSummary,
    Decision,
    DecisionHistory,
    DecisionStatus,
    PolicyBands,
    RECOMMENDATION_OF,
    Recommendation,
    RiskBand,
    OfficerDecision,
    PortfolioStats,
    ReviewRequest,
    ScoreBucket,
    ScoreResponse,
    SMEApplicant,
    StatementRequest,
    UserRole,
)
from services import (
    audit_service,
    borrower_service,
    decision_service,
    model_registry,
    policy_rules,
    policy_service,
)
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
    """Assess an SME application and return a recommendation. Nothing is decided here.

    Three separate things come back:

    * **assessment**: what the model said (score 0-100, probability of default).
    * **policy**: what the active credit policy recommends for that score
      (Approve / Manual Review / Decline) and who may approve.
    * **officer_decision**: always ``Pending``. An authorised officer records
      the decision with ``POST /score/applications/{id}/decision``.

    ``decision`` is the recommendation in the wording used since 1.0
    (``Approved`` means "recommend approve"); it is not a final decision.

    The application is filed under a borrower: the one named by
    ``borrower_public_id``, else the one holding the given CNIC or NTN, else a
    new one. ``rescore_of_application_id`` re-assesses an undecided application:
    a new application is stored, the earlier one is kept unchanged and marked
    Superseded, and the audit trail records who re-scored it and which inputs
    changed.
    """
    evidence = _turnover_evidence(applicant)

    previous: Application | None = None
    if applicant.rescore_of_application_id is not None:
        previous = _load_application(applicant.rescore_of_application_id, db, for_update=True)
        if previous.decision_status not in decision_service.OPEN_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Application {previous.id} is {previous.decision_status}. Only an "
                    "undecided application can be re-scored; open a new application instead."
                ),
            )
        if previous.borrower is None:  # pragma: no cover - guarded by NOT NULL
            raise HTTPException(status_code=409, detail="The application has no borrower.")
        if (
            applicant.borrower_public_id is not None
            and applicant.borrower_public_id != previous.borrower.public_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Application {previous.id} belongs to borrower "
                    f"{previous.borrower.public_id}. A re-score stays with that borrower."
                ),
            )
        applicant = applicant.model_copy(
            update={"borrower_public_id": previous.borrower.public_id}
        )

    borrower, borrower_created = borrower_service.resolve_for_application(
        db, applicant, actor=officer, context=audit
    )
    served_model = model_registry.ensure_registered(db, scorer, audit)
    policy = policy_service.active_policy(db)

    # Model: the assessment. Policy: what it recommends. Neither decides.
    result = scorer.score(applicant, policy_service.bands_of(policy))
    evaluation = policy_service.evaluate(policy, result.risk_score, applicant.loan_amount_pkr)

    prior = db.execute(
        select(func.count(Application.id), func.max(Application.id)).where(
            Application.borrower_id == borrower.id
        )
    ).one()

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
        raw_pd=result.probability_of_default,
        calibrated_pd=result.calibrated_pd,
        risk_band=evaluation.risk_band.value,
        # The recommendation, in the stored wording. Not a decision.
        decision=evaluation.recommendation.value,
        policy_id=evaluation.policy_id,
        policy_version=evaluation.policy_version,
        policy_evaluation=evaluation.snapshot(),
        decision_status=DecisionStatus.PENDING.value,
        scored_by=officer.username,
    )

    db.add(application)
    db.flush()  # assigns the primary key needed by the explanation payload

    explanation = scorer.build_explanation(
        result,
        application_id=application.id,
        business_name=application.business_name,
        applicant=applicant,
        policy_version=evaluation.policy_version,
    )
    # Persisted so the rationale can be retrieved later even if the model
    # is retrained. Not an SBP certification.
    application.shap_explanation_json = json.dumps(explanation.model_dump(mode="json"))
    application.reason_codes = [code.model_dump() for code in explanation.reason_codes]

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
            # Earlier applications on file for this borrower, so repeated
            # attempts for the same business are visible from the first entry.
            "borrower_prior_applications": int(prior[0]),
            "borrower_previous_application_id": prior[1],
            "rescore_of_application_id": previous.id if previous is not None else None,
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
            "probability_of_default_raw": result.probability_of_default,
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
        action=Action.RECOMMENDATION_GENERATED,
        entity_type="application",
        entity_id=application.id,
        actor=officer,
        new={
            "recommendation": RECOMMENDATION_OF[evaluation.recommendation].value,
            "risk_band": evaluation.risk_band.value,
            "decision_status": DecisionStatus.PENDING.value,
        },
        details={
            "policy_id": evaluation.policy_id,
            "policy_version": evaluation.policy_version,
            "policy_name": evaluation.policy_name,
            "triggered_rules": evaluation.triggered_rules,
            "approve_requires": evaluation.approve_requires,
            "authority_reason": evaluation.authority_reason,
            "manager_approval_limit_pkr": evaluation.manager_approval_limit_pkr,
            "risk_score": result.risk_score,
            "reason_codes": [code.code for code in explanation.reason_codes],
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
    if previous is not None:
        decision_service.supersede(db, previous, application, officer=officer, context=audit)

    db.commit()
    db.refresh(application)
    summary = ApplicationSummary.model_validate(application)

    return ScoreResponse(
        application_id=application.id,
        applicant_name=application.applicant_name,
        business_name=application.business_name,
        loan_amount_pkr=application.loan_amount_pkr,
        tenure_months=application.tenure_months,
        monthly_installment_pkr=applicant.monthly_installment_pkr,
        risk_score=application.risk_score,
        decision=evaluation.recommendation,
        risk_band=evaluation.risk_band,
        confidence=result.confidence,
        model_version=application.model_version,
        scoring_engine=application.scoring_engine,
        borrower_id=borrower.id,
        borrower_public_id=borrower.public_id,
        borrower_created=borrower_created,
        probability_of_default=result.calibrated_pd,
        recommendation=summary.recommendation,
        policy_version=application.policy_version,
        decision_status=summary.decision_status,
        assessment=summary.assessment,
        policy=summary.policy,
        officer_decision=summary.officer_decision,
        reason_codes=explanation.reason_codes,
        supersedes_application_id=application.supersedes_application_id,
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
        Decision | None,
        Query(description="Filter by the policy recommendation (legacy wording)."),
    ] = None,
    pending_review: Annotated[
        bool | None,
        Query(description="true: applications still awaiting an officer decision."),
    ] = None,
    final_decision: Annotated[
        OfficerDecision | None,
        Query(description="The officer's decision: Approved or Rejected."),
    ] = None,
    decision_status: Annotated[
        DecisionStatus | None,
        Query(description="Pending, Escalated, Approved, Rejected or Superseded."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ApplicationSummary]:
    """Return scored applications, newest first, for the review dashboard."""
    statement = select(Application).order_by(Application.created_at.desc())
    if decision is not None:
        statement = statement.where(Application.decision == decision.value)
    if pending_review is True:
        statement = statement.where(_is_open())
    elif pending_review is False:
        statement = statement.where(~_is_open())
    if final_decision is not None:
        statement = statement.where(_final_is(final_decision.value))
    if decision_status is not None:
        statement = statement.where(Application.decision_status == decision_status.value)

    applications = db.scalars(statement.offset(offset).limit(limit)).all()
    return [ApplicationSummary.model_validate(app) for app in applications]


_RECOMMENDATION_OF_BAND = {
    RiskBand.HIGH: Recommendation.DECLINE,
    RiskBand.MEDIUM: Recommendation.MANUAL_REVIEW,
    RiskBand.LOW: Recommendation.APPROVE,
}


def _final_is(decision: str):
    """SQL condition: an officer's decision on the application equals ``decision``."""
    return Application.decision_status == decision


def _current():
    """SQL condition: not an assessment that was replaced by a re-score.

    A superseded assessment is kept and listed, but it is not a separate
    application, so the totals leave it out.
    """
    return Application.decision_status != DecisionStatus.SUPERSEDED.value


def _is_open():
    """SQL condition: the application still awaits an officer decision."""
    return Application.decision_status.in_(decision_service.OPEN_STATUSES)


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
    """Counts, exposure, score histogram and open alerts.

    Assessments replaced by a re-score are left out; ``superseded_assessments``
    says how many there are. The histogram's bars are cut on the active
    policy's cut-offs (two bars per band), so no bar mixes recommendations.
    """
    policy = policy_service.active_policy(db)
    bands = policy_service.bands_of(policy)
    buckets = policy_rules.histogram_buckets(bands)
    approved = _final_is(Decision.APPROVED.value)
    rejected = _final_is(Decision.REJECTED.value)
    pending = _is_open()
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
                for _label, lower, upper, _band in buckets
            ],
        ).where(_current())
    ).one()
    total, pending_count, approved_count, rejected_count, exposure, average = totals[:6]
    bucket_counts = totals[6:]

    by_band = dict.fromkeys((band.value for band in Decision), 0)
    for band, count in db.execute(
        select(Application.decision, func.count())
        .where(_current())
        .group_by(Application.decision)
    ):
        by_band[band] = count

    open_filter = Alert.alert_status.in_(ALERT_OPEN_STATUSES)
    open_alerts, worst_drop = db.execute(
        select(func.count(Alert.id), func.max(Alert.score_drop)).where(open_filter)
    ).one()
    db.commit()  # keeps the demo policy if this request was the first to need it

    return PortfolioStats(
        total_applications=total,
        superseded_assessments=db.scalar(
            select(func.count(Application.id)).where(~_current())
        )
        or 0,
        model_decisions=by_band,
        recommendations={
            RECOMMENDATION_OF[Decision(band)].value: count for band, count in by_band.items()
        },
        pending_review=pending_count,
        final_approved=approved_count,
        final_rejected=rejected_count,
        approval_rate=round(approved_count / total * 100, 2) if total else 0.0,
        approved_exposure_pkr=float(exposure),
        average_score=round(float(average), 2) if average is not None else None,
        score_histogram=[
            ScoreBucket(
                label=label,
                lower=lower,
                upper=upper,
                count=count,
                risk_band=band,
                recommendation=_RECOMMENDATION_OF_BAND[band],
            )
            for (label, lower, upper, band), count in zip(buckets, bucket_counts, strict=True)
        ],
        histogram_policy_version=policy.version,
        histogram_bands=PolicyBands(
            decline_max_score=bands.decline_max_score,
            manual_review_max_score=bands.manual_review_max_score,
            approve_above_score=bands.manual_review_max_score,
            source="active_policy",
        ),
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
    "/applications/{application_id}/decision",
    response_model=ApplicationSummary,
    summary="Record the officer's decision: approve, reject or escalate (manager or admin)",
)
@router.post(
    "/applications/{application_id}/review",
    response_model=ApplicationSummary,
    summary="Same as /decision; the route name used before 2.0",
)
async def decide_application(
    application_id: int, body: ReviewRequest, db: DbSession, officer: Manager, audit: Audit
) -> ApplicationSummary:
    """Record the human decision on an application, with the reason, once.

    Every application needs this, whatever the policy recommended: a
    recommendation of Approve is not an approval. Authority is checked here,
    under the policy version the application was assessed under:

    * a manager may reject, may approve up to the manager limit, and may
      escalate to an admin;
    * approving above the limit, approving against a Decline recommendation
      (when the policy requires it) and deciding an escalated application
      need an admin.

    A refused action returns ``403`` and is itself written to the audit trail.
    A recorded decision cannot be changed (``409``). The assessment, the
    recommendation and the model and policy versions are left exactly as they
    were stored at scoring time.
    """
    # Row lock, so two officers deciding at once cannot both record a decision.
    application = _load_application(application_id, db, for_update=True)
    decision_service.record_action(
        db, application, body.decision, body.note, officer=officer, context=audit
    )
    db.commit()
    db.refresh(application)
    return ApplicationSummary.model_validate(application)


@router.get(
    "/applications/{application_id}/decision-history",
    response_model=DecisionHistory,
    summary="Every assessment, recommendation and decision event for an application",
)
async def decision_history(application_id: int, db: DbSession) -> DecisionHistory:
    """The application's re-score chain and its audited events, oldest first.

    ``assessments`` lists the application and every assessment it replaced or
    was replaced by, each with the score, model version and policy version it
    was given. ``events`` are the audit entries on those applications: created,
    scored, recommendation generated, re-scored, escalated, decided, refused.
    """
    return decision_service.history(db, _load_application(application_id, db))


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
