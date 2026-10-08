"""The deterministic EWS engine: trend, signals, state and actions (no database)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from schemas import EWSState, TrendDirection
from services import ews_engine
from services.ews_engine import (
    INSUFFICIENT_HISTORY,
    SCORE_DROP_CRITICAL,
    SCORE_DROP_WARNING,
    TREND_MIN_OBSERVATIONS,
    Facility,
    assess,
    compute_trend,
    ols_slope,
)

FACILITY = Facility(
    baseline_score=80.0, facility_amount_pkr=1_200_000, underwritten_monthly_cash_flow=200_000
)


@dataclass
class Obs:
    month_number: int
    monthly_score: float
    installment_status: str = "On Time"
    days_late: int | None = None
    bureau_balance: float = 1_000_000
    pos_cash_balance: float = 200_000
    score_source: str = "ews_rule_adjusted"
    observation_date: date | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = self.month_number


def _months(*scores: float, **fields) -> list[Obs]:
    return [Obs(month, score, **fields) for month, score in enumerate(scores, start=1)]


# --- trend ---------------------------------------------------------------------------


def test_no_observation_is_insufficient_data() -> None:
    trend = compute_trend(80.0, [])
    assert trend.direction is TrendDirection.INSUFFICIENT_DATA
    assert trend.latest_score is None and trend.total_deterioration is None
    assert trend.message == INSUFFICIENT_HISTORY


def test_one_observation_gives_a_deterioration_but_never_a_trend() -> None:
    trend = compute_trend(80.0, _months(40.0))
    assert trend.total_deterioration == 40.0
    assert trend.previous_score is None and trend.recent_deterioration is None
    assert trend.slope_points_per_month is None
    assert trend.direction is TrendDirection.INSUFFICIENT_DATA
    assert trend.message == INSUFFICIENT_HISTORY


def test_two_observations_give_recent_deterioration_but_no_trend() -> None:
    trend = compute_trend(80.0, _months(78.0, 60.0))
    assert trend.previous_score == 78.0
    assert trend.recent_deterioration == 18.0
    assert trend.total_deterioration == 20.0
    assert trend.direction is TrendDirection.INSUFFICIENT_DATA


@pytest.mark.parametrize(
    ("scores", "direction"),
    [
        ((80.0, 76.0, 72.0), TrendDirection.DETERIORATING),
        ((60.0, 64.0, 68.0), TrendDirection.IMPROVING),
        ((80.0, 79.5, 80.2, 79.8), TrendDirection.STABLE),
    ],
)
def test_three_or_more_observations_give_a_direction(scores, direction) -> None:
    trend = compute_trend(80.0, _months(*scores))
    assert trend.observations == len(scores) >= TREND_MIN_OBSERVATIONS
    assert trend.direction is direction
    assert trend.message is None


def test_the_slope_is_ordinary_least_squares() -> None:
    # y = 70 - 2x exactly, and a noisy line whose OLS slope is known by hand.
    assert ols_slope([(1, 68), (2, 66), (3, 64)]) == pytest.approx(-2.0)
    assert ols_slope([(1, 10), (2, 14), (4, 15)]) == pytest.approx(1.5)
    with pytest.raises(ValueError):
        ols_slope([(2, 10), (2, 12)])


def test_months_are_ordered_and_gaps_are_respected() -> None:
    # Recorded out of order with a gap: month 1, 5, 3.
    rows = [Obs(1, 80.0), Obs(5, 72.0), Obs(3, 76.0)]
    trend = compute_trend(80.0, rows)
    assert trend.latest_score == 72.0 and trend.previous_score == 76.0
    assert trend.slope_points_per_month == pytest.approx(-2.0)


def test_the_baseline_is_not_a_point_of_the_slope() -> None:
    # Flat months after a fall from origination: deteriorated, but the trend is stable.
    trend = compute_trend(80.0, _months(50.0, 50.0, 50.0))
    assert trend.total_deterioration == 30.0
    assert trend.direction is TrendDirection.STABLE


# --- signals ------------------------------------------------------------------------


def _codes(rows: list[Obs]) -> list[str]:
    return assess(FACILITY, rows).reason_codes


def test_a_healthy_month_has_no_signal_and_is_normal() -> None:
    result = assess(FACILITY, _months(80.0))
    assert result.signals == ()
    assert result.state is EWSState.NORMAL
    assert result.recommended_actions == ["Continue routine monthly monitoring."]


def test_payment_delay_compares_with_the_month_before() -> None:
    rows = [Obs(1, 80.0), Obs(2, 74.0, installment_status="Late 1-29", days_late=12)]
    result = assess(FACILITY, rows)
    signal = result.signals[0]
    assert signal.code == "PAYMENT_DELAY_INCREASED"
    assert "On Time (month 1)" in signal.evidence and "Late 1-29 (month 2)" in signal.evidence
    assert signal.values["current_days_late"] == 12
    assert result.state is EWSState.WATCH


def test_more_days_late_in_the_same_bucket_is_a_delay_signal() -> None:
    rows = [
        Obs(1, 74.0, installment_status="Late 1-29", days_late=5),
        Obs(2, 74.0, installment_status="Late 1-29", days_late=25),
    ]
    assert _codes(rows) == ["PAYMENT_DELAY_INCREASED"]


def test_the_first_month_compares_with_origination() -> None:
    rows = [Obs(1, 80.0, bureau_balance=1_400_000, pos_cash_balance=100_000)]
    result = assess(FACILITY, rows)
    codes = result.reason_codes
    assert codes[:2] == ["BALANCE_INCREASED", "POS_CASH_FLOW_DECLINED"]
    assert "the facility amount" in result.signals[0].evidence
    assert "underwritten at origination" in result.signals[1].evidence
    assert codes[-1] == "MULTIPLE_NEGATIVE_SIGNALS"


def test_balance_and_pos_thresholds_are_strict() -> None:
    # Exactly 5% up and exactly 20% down do not fire.
    rows = [Obs(1, 80.0), Obs(2, 80.0, bureau_balance=1_050_000, pos_cash_balance=160_000)]
    assert _codes(rows) == []
    rows = [Obs(1, 80.0), Obs(2, 80.0, bureau_balance=1_050_001, pos_cash_balance=159_999)]
    assert _codes(rows) == [
        "BALANCE_INCREASED",
        "POS_CASH_FLOW_DECLINED",
        "MULTIPLE_NEGATIVE_SIGNALS",
    ]


def test_score_decline_fires_strictly_above_the_warning_drop() -> None:
    assert "RISK_SCORE_DECLINED" not in _codes(_months(80.0 - SCORE_DROP_WARNING))
    rows = _months(80.0 - SCORE_DROP_WARNING - 0.01)
    result = assess(FACILITY, rows)
    assert result.reason_codes == ["RISK_SCORE_DECLINED"]
    assert result.state is EWSState.WARNING
    assert "below the origination baseline 80" in result.signals[0].evidence


def test_a_deteriorating_trend_is_a_signal_and_a_warning() -> None:
    result = assess(FACILITY, _months(79.0, 76.0, 73.0))
    assert result.reason_codes == ["RISK_TREND_DETERIORATING"]
    assert result.state is EWSState.WARNING
    assert result.signals[0].values["observations"] == 3


def test_one_bad_month_is_never_called_a_deteriorating_trend() -> None:
    result = assess(FACILITY, _months(30.0))
    assert "RISK_TREND_DETERIORATING" not in result.reason_codes
    assert result.trend.direction is TrendDirection.INSUFFICIENT_DATA


# --- state --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("On Time", EWSState.NORMAL),
        ("Late 1-29", EWSState.WATCH),
        ("Late 30-59", EWSState.WARNING),
        ("Late 60-89", EWSState.CRITICAL),
        ("Default", EWSState.CRITICAL),
    ],
)
def test_the_repayment_bucket_sets_a_floor_on_the_state(status: str, state: EWSState) -> None:
    # Two months in the same bucket, score unchanged: only the bucket speaks.
    rows = [Obs(1, 80.0, installment_status=status), Obs(2, 80.0, installment_status=status)]
    assert assess(FACILITY, rows).state is state


def test_a_drop_of_twice_the_warning_is_critical() -> None:
    result = assess(FACILITY, _months(80.0 - SCORE_DROP_CRITICAL))
    assert result.state is EWSState.CRITICAL
    assert any("critical at" in reason for reason in result.state_reasons)


def test_states_are_separate_from_credit_bands() -> None:
    # A Low-Risk-band score that fell 31 points is CRITICAL; a Medium-band
    # score that has not moved is NORMAL.
    high = Facility(95.0, 1_000_000, 200_000)
    assert assess(high, [Obs(1, 64.0)]).state is EWSState.CRITICAL
    middle = Facility(55.0, 1_000_000, 200_000)
    assert assess(middle, [Obs(1, 55.0)]).state is EWSState.NORMAL


def test_only_warning_and_critical_raise_alerts() -> None:
    assert not assess(FACILITY, _months(80.0)).raises_alert
    assert not assess(FACILITY, [Obs(1, 75.0, installment_status="Late 1-29")]).raises_alert
    assert assess(FACILITY, [Obs(1, 75.0, installment_status="Late 30-59")]).raises_alert


def test_every_state_recommends_and_none_acts() -> None:
    for state, actions in ews_engine.RECOMMENDED_ACTIONS.items():
        assert actions, state
    critical = " ".join(ews_engine.RECOMMENDED_ACTIONS[EWSState.CRITICAL])
    assert "does not classify or restructure" in critical
    assert "does not approve, reject, freeze, restructure" in ews_engine.NO_AUTOMATIC_ACTION


def test_the_engine_is_deterministic() -> None:
    rows = [
        Obs(1, 78.0),
        Obs(2, 70.0, installment_status="Late 1-29", days_late=10, pos_cash_balance=120_000),
        Obs(3, 61.0, installment_status="Late 30-59", days_late=40, bureau_balance=1_300_000),
    ]
    first, second = assess(FACILITY, rows), assess(FACILITY, list(reversed(rows)))
    assert first.as_dict() == second.as_dict()
    assert first.state is EWSState.WARNING
    assert first.reason_codes == [
        "PAYMENT_DELAY_INCREASED",
        "BALANCE_INCREASED",
        # POS rose from month 2 (120k) to month 3 (200k): no POS signal.
        "RISK_SCORE_DECLINED",
        "RISK_TREND_DETERIORATING",
        "MULTIPLE_NEGATIVE_SIGNALS",
    ]


def test_the_methodology_is_published() -> None:
    method = ews_engine.methodology()
    assert method["score_drop_warning"] == SCORE_DROP_WARNING == 15.0
    assert method["score_drop_critical"] == 30.0
    assert method["trend_min_observations"] == 3
    assert method["alert_states"] == [EWSState.WARNING, EWSState.CRITICAL]
    assert any("not a default-prediction model" in note for note in method["notes"])
