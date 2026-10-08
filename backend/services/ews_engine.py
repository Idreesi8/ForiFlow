"""Deterministic EWS analytics: trend, signals, state and recommended actions.

Pure functions over a facility's stored observations. Nothing here touches the
database, a model or the network, so the same history always gives the same
answer and every conclusion can be traced to the figures that produced it.

What this is: rule- and trend-based monitoring of officer-recorded months. What
it is not: a default-prediction model. The thresholds below are monitoring
rules chosen for this project; they were not fitted or validated on SME loan
outcomes. The EWS state is separate from the credit risk band and from any
credit decision, and the engine never changes a facility.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from schemas import EWSState, InstallmentStatus, TrendDirection
from services.ews_service import ALERT_SCORE_DROP_THRESHOLD

# --- methodology --------------------------------------------------------------------

# Total deterioration (baseline minus latest) above this is WARNING. The same
# 15 points the EWS has alerted on since 1.0.
SCORE_DROP_WARNING: float = ALERT_SCORE_DROP_THRESHOLD
# At or above this it is CRITICAL: twice the warning drop, the point at which
# the EWS has advised escalation to recovery since 1.0.
SCORE_DROP_CRITICAL: float = 2 * ALERT_SCORE_DROP_THRESHOLD
# A trend is computed only from this many monthly observations.
TREND_MIN_OBSERVATIONS: int = 3
# OLS slope, in score points per month, beyond which the trend has a direction.
TREND_SLOPE_POINTS_PER_MONTH: float = 1.0
# Bureau balance this much above the previous month (or the facility amount).
BALANCE_INCREASE_PCT: float = 5.0
# POS inflow this much below the previous month (or the underwritten cash flow).
POS_DECLINE_PCT: float = 20.0

# States that raise an alert. WATCH is listed on the dashboard but not alerted.
ALERT_STATES: tuple[EWSState, ...] = (EWSState.WARNING, EWSState.CRITICAL)
STATE_RANK: dict[EWSState, int] = {
    EWSState.NORMAL: 0,
    EWSState.WATCH: 1,
    EWSState.WARNING: 2,
    EWSState.CRITICAL: 3,
}

STATUS_RANK: dict[str, int] = {
    InstallmentStatus.ON_TIME.value: 0,
    InstallmentStatus.LATE_1_29.value: 1,
    InstallmentStatus.LATE_30_59.value: 2,
    InstallmentStatus.LATE_60_89.value: 3,
    InstallmentStatus.DEFAULT.value: 4,
}
CRITICAL_STATUSES: frozenset[str] = frozenset(
    {InstallmentStatus.LATE_60_89.value, InstallmentStatus.DEFAULT.value}
)

INSUFFICIENT_HISTORY = "Insufficient history for multi-month trend"

SIGNAL_LABELS: dict[str, str] = {
    "PAYMENT_DELAY_INCREASED": "Payment delay increased",
    "BALANCE_INCREASED": "Bureau balance increased",
    "POS_CASH_FLOW_DECLINED": "POS cash flow declined",
    "RISK_SCORE_DECLINED": "Monitored score declined past the warning drop",
    "RISK_TREND_DETERIORATING": "Monitored score trend is deteriorating",
    "MULTIPLE_NEGATIVE_SIGNALS": "Several negative signals at once",
}

NO_AUTOMATIC_ACTION = (
    "These are recommendations. ForiFlow does not approve, reject, freeze, "
    "restructure or classify a facility; the bank's own process decides."
)

RECOMMENDED_ACTIONS: dict[EWSState, tuple[str, ...]] = {
    EWSState.NORMAL: ("Continue routine monthly monitoring.",),
    EWSState.WATCH: (
        "Note the change on the credit file and review it at the next monthly observation.",
        "Check the next POS settlement and bureau figures for the same movement.",
    ),
    EWSState.WARNING: (
        "Relationship manager to contact the borrower within 7 days.",
        "Verify POS settlements and the bank statement for the last three months.",
        "Obtain an updated bureau extract (ForiFlow has no live ECIB feed).",
    ),
    EWSState.CRITICAL: (
        "Refer the facility to the bank's remedial or recovery unit within 48 hours.",
        "Obtain an updated bureau extract (ForiFlow has no live ECIB feed).",
        "Consider whether the bank's restructuring or classification process applies "
        "under SBP Prudential Regulations. ForiFlow does not classify or restructure.",
    ),
}

# A suggested follow-up window per alert severity, in days. Shown, never set.
SUGGESTED_DUE_DAYS: dict[EWSState, int] = {EWSState.WARNING: 7, EWSState.CRITICAL: 2}


def methodology() -> dict[str, Any]:
    """The thresholds and caveats, for the API and the dashboard."""
    return {
        "score_drop_warning": SCORE_DROP_WARNING,
        "score_drop_critical": SCORE_DROP_CRITICAL,
        "trend_min_observations": TREND_MIN_OBSERVATIONS,
        "trend_slope_points_per_month": TREND_SLOPE_POINTS_PER_MONTH,
        "balance_increase_pct": BALANCE_INCREASE_PCT,
        "pos_decline_pct": POS_DECLINE_PCT,
        "alert_states": list(ALERT_STATES),
        "critical_statuses": sorted(CRITICAL_STATUSES, key=STATUS_RANK.get),
        "notes": [
            "Rule- and trend-based monitoring of officer-recorded months; not a "
            "default-prediction model.",
            "The thresholds are project monitoring rules, not values fitted or "
            "validated on SME loan outcomes.",
            "The EWS state is separate from the credit risk band and from any credit decision.",
            f"A trend direction needs at least {TREND_MIN_OBSERVATIONS} monthly observations.",
            NO_AUTOMATIC_ACTION,
        ],
    }


# --- inputs -------------------------------------------------------------------------


class Observation(Protocol):
    """The fields the engine reads from a stored observation (``EWSTracking``)."""

    id: int | None
    month_number: int
    monthly_score: float
    installment_status: str
    days_late: int | None
    bureau_balance: float
    pos_cash_balance: float
    score_source: str
    observation_date: date | None


@dataclass(frozen=True, slots=True)
class Facility:
    """What the engine needs to know about the approved facility itself."""

    baseline_score: float
    facility_amount_pkr: float
    underwritten_monthly_cash_flow: float


# --- outputs ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Trend:
    baseline_score: float
    latest_score: float | None
    previous_score: float | None
    total_deterioration: float | None
    recent_deterioration: float | None
    slope_points_per_month: float | None
    direction: TrendDirection
    observations: int
    min_observations: int = TREND_MIN_OBSERVATIONS

    @property
    def message(self) -> str | None:
        return INSUFFICIENT_HISTORY if self.observations < self.min_observations else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "baseline_score": self.baseline_score,
            "latest_score": self.latest_score,
            "previous_score": self.previous_score,
            "total_deterioration": self.total_deterioration,
            "recent_deterioration": self.recent_deterioration,
            "slope_points_per_month": self.slope_points_per_month,
            "direction": self.direction.value,
            "observations": self.observations,
            "min_observations": self.min_observations,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class Signal:
    code: str
    evidence: str
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return SIGNAL_LABELS[self.code]

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "label": self.label, "evidence": self.evidence, "values": self.values}


@dataclass(frozen=True, slots=True)
class Assessment:
    """The EWS conclusion for a facility after its latest active observation."""

    state: EWSState
    state_reasons: tuple[str, ...]
    signals: tuple[Signal, ...]
    trend: Trend
    latest_observation_id: int | None
    latest_month: int | None

    @property
    def reason_codes(self) -> list[str]:
        return [signal.code for signal in self.signals]

    @property
    def recommended_actions(self) -> list[str]:
        return list(RECOMMENDED_ACTIONS[self.state])

    @property
    def raises_alert(self) -> bool:
        return self.state in ALERT_STATES

    def as_dict(self) -> dict[str, Any]:
        """Stored on the observation, so the record shows what the EWS concluded then."""
        return {
            "state": self.state.value,
            "state_reasons": list(self.state_reasons),
            "reason_codes": self.reason_codes,
            "signals": [signal.as_dict() for signal in self.signals],
            "trend": self.trend.as_dict(),
            "latest_month": self.latest_month,
        }


# --- the rules ----------------------------------------------------------------------


def _ordered(observations: Sequence[Observation]) -> list[Observation]:
    return sorted(observations, key=lambda row: row.month_number)


def ols_slope(points: Sequence[tuple[float, float]]) -> float:
    """Ordinary least squares slope of y on x. Needs two distinct x values."""
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in points)
    if sxx == 0:
        raise ValueError("The slope needs at least two different months.")
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    return sxy / sxx


def compute_trend(baseline_score: float, observations: Sequence[Observation]) -> Trend:
    """Baseline, latest, deteriorations and, from enough months, the direction.

    The slope uses the monthly observations only. The origination score is the
    baseline the deterioration is measured from, not a point of the slope, so a
    single bad month cannot make a trend.
    """
    rows = _ordered(observations)
    n = len(rows)
    baseline = round(float(baseline_score), 2)
    if n == 0:
        return Trend(baseline, None, None, None, None, None, TrendDirection.INSUFFICIENT_DATA, 0)

    latest = round(float(rows[-1].monthly_score), 2)
    previous = round(float(rows[-2].monthly_score), 2) if n >= 2 else None
    total = round(baseline - latest, 2)
    recent = round(previous - latest, 2) if previous is not None else None

    slope: float | None = None
    direction = TrendDirection.INSUFFICIENT_DATA
    if n >= TREND_MIN_OBSERVATIONS:
        slope = round(ols_slope([(row.month_number, row.monthly_score) for row in rows]), 3)
        if slope <= -TREND_SLOPE_POINTS_PER_MONTH:
            direction = TrendDirection.DETERIORATING
        elif slope >= TREND_SLOPE_POINTS_PER_MONTH:
            direction = TrendDirection.IMPROVING
        else:
            direction = TrendDirection.STABLE
    return Trend(baseline, latest, previous, total, recent, slope, direction, n)


def _pkr(value: float) -> str:
    return f"PKR {value:,.0f}"


def compute_signals(
    facility: Facility, observations: Sequence[Observation], trend: Trend
) -> list[Signal]:
    """The signals the latest observation shows against the one before it.

    The month before is the previous active observation; for the first month it
    is the facility at origination (On Time, balance equal to the facility
    amount, POS inflow equal to the underwritten monthly cash flow).
    """
    rows = _ordered(observations)
    if not rows:
        return []
    latest = rows[-1]
    previous = rows[-2] if len(rows) >= 2 else None
    where = f"month {previous.month_number}" if previous is not None else "origination"
    signals: list[Signal] = []

    # Payment delay.
    prev_status = previous.installment_status if previous is not None else InstallmentStatus.ON_TIME.value
    prev_days = previous.days_late if previous is not None else 0
    latest_rank, prev_rank = STATUS_RANK[latest.installment_status], STATUS_RANK[prev_status]
    days_worse = (
        latest_rank == prev_rank
        and latest.days_late is not None
        and prev_days is not None
        and latest.days_late > prev_days
    )
    if latest_rank > prev_rank or days_worse:
        detail = f"Repayment moved from {prev_status} ({where}) to {latest.installment_status} (month {latest.month_number})"
        if latest.days_late is not None:
            detail += f", {latest.days_late} days late"
        signals.append(
            Signal(
                "PAYMENT_DELAY_INCREASED",
                detail + ".",
                {
                    "previous_status": prev_status,
                    "current_status": latest.installment_status,
                    "previous_days_late": prev_days,
                    "current_days_late": latest.days_late,
                },
            )
        )

    # Bureau balance.
    ref_balance = previous.bureau_balance if previous is not None else facility.facility_amount_pkr
    if ref_balance > 0 and latest.bureau_balance > ref_balance * (1 + BALANCE_INCREASE_PCT / 100):
        change = (latest.bureau_balance / ref_balance - 1) * 100
        basis = f"{where}" if previous is not None else "the facility amount"
        signals.append(
            Signal(
                "BALANCE_INCREASED",
                f"Bureau balance {_pkr(latest.bureau_balance)} is {change:.1f}% above "
                f"{_pkr(ref_balance)} ({basis}); the threshold is {BALANCE_INCREASE_PCT:g}%.",
                {
                    "reference_balance_pkr": round(ref_balance, 2),
                    "current_balance_pkr": round(latest.bureau_balance, 2),
                    "change_pct": round(change, 1),
                },
            )
        )

    # POS inflow.
    ref_pos = previous.pos_cash_balance if previous is not None else facility.underwritten_monthly_cash_flow
    if ref_pos > 0 and latest.pos_cash_balance < ref_pos * (1 - POS_DECLINE_PCT / 100):
        change = (1 - latest.pos_cash_balance / ref_pos) * 100
        basis = f"{where}" if previous is not None else "the cash flow underwritten at origination"
        signals.append(
            Signal(
                "POS_CASH_FLOW_DECLINED",
                f"POS inflow {_pkr(latest.pos_cash_balance)} is {change:.1f}% below "
                f"{_pkr(ref_pos)} ({basis}); the threshold is {POS_DECLINE_PCT:g}%.",
                {
                    "reference_pos_pkr": round(ref_pos, 2),
                    "current_pos_pkr": round(latest.pos_cash_balance, 2),
                    "decline_pct": round(change, 1),
                },
            )
        )

    # Score against the baseline.
    if trend.total_deterioration is not None and trend.total_deterioration > SCORE_DROP_WARNING:
        signals.append(
            Signal(
                "RISK_SCORE_DECLINED",
                f"Monitored score {trend.latest_score:g} is {trend.total_deterioration:g} points "
                f"below the origination baseline {trend.baseline_score:g} "
                f"(warning above {SCORE_DROP_WARNING:g}).",
                {
                    "baseline_score": trend.baseline_score,
                    "current_score": trend.latest_score,
                    "total_deterioration": trend.total_deterioration,
                },
            )
        )

    # Trend over several months.
    if trend.direction is TrendDirection.DETERIORATING:
        signals.append(
            Signal(
                "RISK_TREND_DETERIORATING",
                f"Over {trend.observations} months the monitored score falls "
                f"{abs(trend.slope_points_per_month or 0):g} points a month "
                f"(least-squares slope; threshold {TREND_SLOPE_POINTS_PER_MONTH:g}).",
                {
                    "slope_points_per_month": trend.slope_points_per_month,
                    "observations": trend.observations,
                },
            )
        )

    if len(signals) >= 2:
        codes = [signal.code for signal in signals]
        signals.append(
            Signal(
                "MULTIPLE_NEGATIVE_SIGNALS",
                f"{len(codes)} signals in month {latest.month_number}: {', '.join(codes)}.",
                {"signals": codes},
            )
        )
    return signals


def classify(
    observations: Sequence[Observation], trend: Trend, signals: Sequence[Signal]
) -> tuple[EWSState, list[str]]:
    """The state and the reasons for it. The worst condition met decides."""
    rows = _ordered(observations)
    if not rows:
        return EWSState.NORMAL, ["No monitoring month recorded yet."]
    latest = rows[-1]
    codes = {signal.code for signal in signals}
    drop = trend.total_deterioration or 0.0

    critical: list[str] = []
    if latest.installment_status in CRITICAL_STATUSES:
        critical.append(f"Latest month is {latest.installment_status}.")
    if drop >= SCORE_DROP_CRITICAL:
        critical.append(f"Score is {drop:g} points below baseline (critical at {SCORE_DROP_CRITICAL:g}).")
    if critical:
        return EWSState.CRITICAL, critical

    warning: list[str] = []
    if drop > SCORE_DROP_WARNING:
        warning.append(f"Score is {drop:g} points below baseline (warning above {SCORE_DROP_WARNING:g}).")
    if latest.installment_status == InstallmentStatus.LATE_30_59.value:
        warning.append("Latest month is Late 30-59.")
    if "RISK_TREND_DETERIORATING" in codes:
        warning.append("The multi-month trend is deteriorating.")
    if "MULTIPLE_NEGATIVE_SIGNALS" in codes:
        warning.append("Several negative signals at once.")
    if warning:
        return EWSState.WARNING, warning

    watch: list[str] = []
    if latest.installment_status == InstallmentStatus.LATE_1_29.value:
        watch.append("Latest month is Late 1-29.")
    for signal in signals:
        watch.append(f"{signal.label}.")
    if watch:
        return EWSState.WATCH, watch
    return EWSState.NORMAL, ["No warning signal in the latest month."]


def assess(facility: Facility, observations: Sequence[Observation]) -> Assessment:
    """Trend, signals and state of a facility from its active observations."""
    rows = _ordered(observations)
    trend = compute_trend(facility.baseline_score, rows)
    signals = compute_signals(facility, rows, trend)
    state, reasons = classify(rows, trend, signals)
    latest = rows[-1] if rows else None
    return Assessment(
        state=state,
        state_reasons=tuple(reasons),
        signals=tuple(signals),
        trend=trend,
        latest_observation_id=latest.id if latest is not None else None,
        latest_month=latest.month_number if latest is not None else None,
    )


def facility_of(application: Any) -> Facility:
    """The engine's view of an approved application."""
    return Facility(
        baseline_score=float(application.risk_score),
        facility_amount_pkr=float(application.loan_amount_pkr),
        underwritten_monthly_cash_flow=float(application.cash_flow_proxy),
    )
