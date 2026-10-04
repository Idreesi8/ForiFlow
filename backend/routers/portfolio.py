"""Portfolio analytics: collections, arrears, risk and concentration."""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from models.database import Alert, Application, EWSTracking, get_db
from schemas import (
    AlertStatus,
    Decision,
    DecisionMatrixRow,
    InstallmentStatus,
    PortfolioSummary,
    SectorRow,
    StatusExposure,
)
from services.auth_service import get_current_user

router = APIRouter(
    prefix="/portfolio",
    tags=["Portfolio"],
    dependencies=[Depends(get_current_user)],
)

DbSession = Annotated[Session, Depends(get_db)]

SECTOR_NOT_RECORDED = "Not recorded"
# An installment such as 20,833.33 is paid as 20,833; that gap is not arrears.
ROUNDING_TOLERANCE_PKR = 1.0
# Latest-month statuses counted in portfolio at risk (30 or more days late).
PAR30_STATUSES = {
    InstallmentStatus.LATE_30_59.value,
    InstallmentStatus.LATE_60_89.value,
    InstallmentStatus.DEFAULT.value,
}


def _final_is(decision: str):
    """SQL condition: the model's band, or the officer's call on Manual Review."""
    return or_(
        Application.decision == decision,
        and_(
            Application.decision == Decision.MANUAL_REVIEW.value,
            Application.review_decision == decision,
        ),
    )


@router.get(
    "/summary",
    response_model=PortfolioSummary,
    summary="Collections, arrears, portfolio at risk and sector concentration",
)
async def portfolio_summary(db: DbSession) -> PortfolioSummary:
    """Repayment position of every approved facility.

    Read from the monthly observations officers record under EWS monitoring.
    Nothing here is estimated: a month without a recorded amount is counted in
    ``months_without_amount`` and left out of the collection figures.
    """
    approved = _final_is(Decision.APPROVED.value)
    rejected = _final_is(Decision.REJECTED.value)

    # One row per approved facility with what was due and paid in recorded months.
    has_amount = EWSTracking.amount_paid_pkr.is_not(None)
    facilities = db.execute(
        select(
            Application.id,
            Application.loan_amount_pkr,
            Application.tenure_months,
            Application.business_sector,
            func.count(EWSTracking.id),
            func.count(case((has_amount, 1))),
            func.coalesce(func.sum(EWSTracking.amount_paid_pkr), 0.0),
        )
        .outerjoin(EWSTracking, EWSTracking.borrower_id == Application.id)
        .where(approved)
        .group_by(Application.id)
    ).all()

    # The status of each facility's latest recorded month.
    latest_month = (
        select(
            EWSTracking.borrower_id.label("borrower_id"),
            func.max(EWSTracking.month_number).label("month_number"),
        )
        .group_by(EWSTracking.borrower_id)
        .subquery()
    )
    latest_status = dict(
        db.execute(
            select(EWSTracking.borrower_id, EWSTracking.installment_status).join(
                latest_month,
                and_(
                    EWSTracking.borrower_id == latest_month.c.borrower_id,
                    EWSTracking.month_number == latest_month.c.month_number,
                ),
            )
        ).all()
    )

    disbursed = due = collected = overdue = outstanding = 0.0
    monitored = months_with = months_without = 0
    monitored_outstanding = at_risk_outstanding = 0.0
    by_status: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    sector_overdue: dict[str, float] = defaultdict(float)

    for app_id, loan, tenure, sector, months, months_paid, paid in facilities:
        installment = loan / max(tenure, 1)
        facility_due = installment * months_paid
        facility_overdue = max(facility_due - paid, 0.0)
        if facility_overdue < ROUNDING_TOLERANCE_PKR:
            facility_overdue = 0.0  # a payment typed in whole rupees is not arrears
        facility_outstanding = max(loan - paid, 0.0)

        disbursed += loan
        due += facility_due
        collected += paid
        overdue += facility_overdue
        outstanding += facility_outstanding
        months_with += months_paid
        months_without += months - months_paid
        sector_overdue[sector or SECTOR_NOT_RECORDED] += facility_overdue

        status_label = latest_status.get(app_id)
        if status_label is not None:
            monitored += 1
            monitored_outstanding += facility_outstanding
            by_status[status_label][0] += 1
            by_status[status_label][1] += facility_outstanding
            if status_label in PAR30_STATUSES:
                at_risk_outstanding += facility_outstanding

    defaulted = by_status.get(InstallmentStatus.DEFAULT.value, [0, 0.0])

    matrix = {
        band: {"approved": 0, "rejected": 0, "pending": 0} for band in Decision
    }
    outcome = case((approved, "approved"), (rejected, "rejected"), else_="pending")
    for band, result, count in db.execute(
        select(Application.decision, outcome, func.count()).group_by(
            Application.decision, outcome
        )
    ):
        matrix[Decision(band)][result] = count

    open_alerts_by_sector: dict[str, int] = defaultdict(int)
    for sector, count in db.execute(
        select(Application.business_sector, func.count(Alert.id))
        .join(Alert, Alert.borrower_id == Application.id)
        .where(Alert.alert_status != AlertStatus.RESOLVED.value)
        .group_by(Application.business_sector)
    ):
        open_alerts_by_sector[sector or SECTOR_NOT_RECORDED] = count

    sectors = [
        SectorRow(
            sector=sector or SECTOR_NOT_RECORDED,
            applications=total,
            approved=approved_count,
            approval_rate=round(approved_count / total * 100, 1) if total else 0.0,
            approved_exposure_pkr=float(exposure),
            average_score=round(float(average), 2),
            overdue_pkr=round(sector_overdue.get(sector or SECTOR_NOT_RECORDED, 0.0), 2),
            open_alerts=open_alerts_by_sector.get(sector or SECTOR_NOT_RECORDED, 0),
        )
        for sector, total, approved_count, exposure, average in db.execute(
            select(
                Application.business_sector,
                func.count(Application.id),
                func.count(case((approved, 1))),
                func.coalesce(func.sum(case((approved, Application.loan_amount_pkr))), 0.0),
                func.avg(Application.risk_score),
            ).group_by(Application.business_sector)
        )
    ]
    sectors.sort(key=lambda row: (-row.approved_exposure_pkr, row.sector))

    return PortfolioSummary(
        approved_facilities=len(facilities),
        monitored_facilities=monitored,
        disbursed_pkr=round(disbursed, 2),
        due_pkr=round(due, 2),
        collected_pkr=round(collected, 2),
        collection_rate=round(collected / due * 100, 1) if due > 0 else None,
        overdue_pkr=round(overdue, 2),
        outstanding_pkr=round(outstanding, 2),
        defaulted_facilities=int(defaulted[0]),
        defaulted_outstanding_pkr=round(defaulted[1], 2),
        par30=(
            round(at_risk_outstanding / monitored_outstanding * 100, 1)
            if monitored_outstanding > 0
            else None
        ),
        months_with_amount=months_with,
        months_without_amount=months_without,
        latest_status=[
            StatusExposure(
                status=status_value,
                facilities=int(by_status[status_value.value][0]),
                outstanding_pkr=round(by_status[status_value.value][1], 2),
            )
            for status_value in InstallmentStatus
        ],
        decision_matrix=[
            DecisionMatrixRow(model_decision=band, **matrix[band])
            for band in (Decision.APPROVED, Decision.MANUAL_REVIEW, Decision.REJECTED)
        ],
        sectors=sectors,
    )
