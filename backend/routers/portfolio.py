"""Portfolio analytics: collections, arrears, risk and concentration."""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timezone
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
    Reminder,
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
# Allowed once per recorded month.
ROUNDING_TOLERANCE_PKR = 1.0
# Latest-month statuses counted in portfolio at risk (30 or more days late).
PAR30_STATUSES = {
    InstallmentStatus.LATE_30_59.value,
    InstallmentStatus.LATE_60_89.value,
    InstallmentStatus.DEFAULT.value,
}


def _final_is(decision: str):
    """SQL condition: an officer's decision on the application equals ``decision``."""
    return Application.decision_status == decision


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
        if facility_overdue <= ROUNDING_TOLERANCE_PKR * months_paid:
            facility_overdue = 0.0  # payments typed in whole rupees are not arrears
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
        select(Application.decision, outcome, func.count())
        .where(Application.decision_status != "Superseded")
        .group_by(Application.decision, outcome)
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
            )
            .where(Application.decision_status != "Superseded")
            .group_by(Application.business_sector)
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


# A reminder is drafted this many days before an installment falls due.
REMINDER_LEAD_DAYS = 7


def _add_months(start: date, months: int) -> date:
    """The same day ``months`` later, or the month's last day if it is shorter."""
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _money(value: float) -> str:
    return f"PKR {value:,.0f}"


def _messages(
    kind: str,
    name: str,
    business: str,
    number: int | None,
    installment: float,
    due: date | None,
    arrears: float,
) -> tuple[str, str]:
    """The reminder in English and in Roman Urdu. Polite, factual, no threats."""
    when = f"{due:%d %b %Y}" if due else ""
    if kind == "arrears":
        english = (
            f"Assalam-o-Alaikum {name}. Our records for {business} show {_money(arrears)} "
            "still unpaid from earlier installments. Please arrange the payment or "
            "contact your branch. If you have already paid, please ignore this message."
        )
        urdu = (
            f"Assalam-o-Alaikum {name}. Hamare record ke mutabiq {business} ki pichli "
            f"qiston mein se {_money(arrears)} abhi baqi hai. Meharbani farma kar adaigi "
            "kar dein ya apni branch se rabta karein. Agar aap ada kar chuke hain to is "
            "paigham ko nazar-andaz kar dein."
        )
        return english, urdu

    verb_en = "was due on" if kind == "overdue" else "is due on"
    verb_ur = "ko wajib-ul-ada thi" if kind == "overdue" else "ko wajib-ul-ada hai"
    english = (
        f"Assalam-o-Alaikum {name}. Installment {number} of {_money(installment)} for "
        f"{business} {verb_en} {when}."
    )
    urdu = (
        f"Assalam-o-Alaikum {name}. {business} ki qist number {number}, "
        f"{_money(installment)}, {when} {verb_ur}."
    )
    if arrears > 0:
        english += f" {_money(arrears)} from earlier installments is also unpaid."
        urdu += f" Pichli qiston ke {_money(arrears)} bhi baqi hain."
    english += " If you have already paid, please ignore this message."
    urdu += " Agar aap ada kar chuke hain to is paigham ko nazar-andaz kar dein."
    return english, urdu


@router.get(
    "/reminders",
    response_model=list[Reminder],
    summary="Payment reminders to send to borrowers",
)
async def payment_reminders(db: DbSession) -> list[Reminder]:
    """Installments past due, due within a week, or unpaid from earlier months.

    The schedule runs monthly from the day the facility was approved (ForiFlow
    stores no separate disbursement date). An installment counts as handled
    once an officer has recorded that month under EWS monitoring. ForiFlow
    drafts the message; it does not send anything.
    """
    today = datetime.now(timezone.utc).date()
    has_amount = EWSTracking.amount_paid_pkr.is_not(None)
    facilities = db.execute(
        select(
            Application,
            func.coalesce(func.max(EWSTracking.month_number), 0),
            func.count(case((has_amount, 1))),
            func.coalesce(func.sum(EWSTracking.amount_paid_pkr), 0.0),
        )
        .outerjoin(EWSTracking, EWSTracking.borrower_id == Application.id)
        .where(_final_is(Decision.APPROVED.value))
        .group_by(Application.id)
    ).all()

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

    reminders: list[Reminder] = []
    for application, recorded_until, months_paid, paid in facilities:
        status_label = latest_status.get(application.id)
        if status_label == InstallmentStatus.DEFAULT.value:
            continue  # with remedial management, not a reminder
        installment = application.loan_amount_pkr / max(application.tenure_months, 1)
        arrears = max(installment * months_paid - paid, 0.0)
        if arrears <= ROUNDING_TOLERANCE_PKR * months_paid:
            arrears = 0.0

        approved_on = (application.reviewed_at or application.created_at).date()
        number = recorded_until + 1 if recorded_until < application.tenure_months else None
        due = _add_months(approved_on, number) if number else None
        days = (due - today).days if due else None

        if days is not None and days < 0:
            kind = "overdue"
        elif days is not None and days <= REMINDER_LEAD_DAYS:
            kind = "due_soon"
        elif arrears > 0:
            kind = "arrears"
        else:
            continue

        english, urdu = _messages(
            kind,
            application.applicant_name,
            application.business_name,
            number,
            installment,
            due,
            arrears,
        )
        reminders.append(
            Reminder(
                application_id=application.id,
                business_name=application.business_name,
                applicant_name=application.applicant_name,
                contact_phone=application.contact_phone,
                kind=kind,
                installment_number=number if kind != "arrears" else None,
                installment_pkr=round(installment, 2),
                due_date=due if kind != "arrears" else None,
                days_until_due=days if kind != "arrears" else None,
                arrears_pkr=round(arrears, 2),
                latest_status=status_label,
                message_en=english,
                message_ur=urdu,
            )
        )

    urgency = {"overdue": 0, "arrears": 1, "due_soon": 2}
    reminders.sort(
        key=lambda item: (urgency[item.kind], item.days_until_due or 0, -item.arrears_pkr)
    )
    return reminders
