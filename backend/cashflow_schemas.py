"""Finite responses for local statement analysis, separate from credit scoring."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')


class CashflowRequest(Record):
    csv: str = Field(min_length=1, max_length=2_000_000)
    date_order: Literal['auto', 'day_first', 'month_first'] = 'auto'


class RepeatedRow(Record):
    first_line: int = Field(ge=2)
    repeated_line: int = Field(ge=2)


class SourceQuality(Record):
    method_version: Literal['cashflow-import-v1'] = 'cashflow-import-v1'
    date_order_requested: Literal['auto', 'day_first', 'month_first']
    date_order_resolved: Literal['day_first', 'month_first', 'iso_or_named', 'identical_day_month']
    ambiguous_numeric_rows: int = Field(ge=0)
    normalised_date_rows: int = Field(ge=0)
    source_rows: int = Field(ge=0)
    repeated_row_candidates: int = Field(ge=0)
    repeated_row_examples: list[RepeatedRow]
    parsed_source_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    notes: list[str]


class Month(Record):
    month: str
    inflow: float = Field(ge=0)
    outflow: float = Field(ge=0)
    transactions: int = Field(ge=0)


Method = Literal['last_month', 'median_6', 'theil_sen_12', 'same_month_last_year']


class Candidate(Record):
    method: Method
    development_mae_pkr: float = Field(ge=0)


class BacktestMonth(Record):
    month: str
    observed_pkr: float = Field(ge=0)
    predicted_pkr: float = Field(ge=0)
    baseline_pkr: float = Field(ge=0)
    lower_pkr: float = Field(ge=0)
    upper_pkr: float = Field(ge=0)


class ReadyForecast(Record):
    status: Literal['ready'] = 'ready'
    selected_method: Method
    candidates: list[Candidate]
    development_months: list[str]
    calibration_months: list[str]
    test_months: list[BacktestMonth]
    empirical_radius_pkr: float = Field(ge=0)
    test_mae_pkr: float = Field(ge=0)
    baseline_test_mae_pkr: float = Field(ge=0)
    test_months_inside_band: int = Field(ge=0, le=6)
    next_month: str
    predicted_pkr: float = Field(ge=0)
    lower_pkr: float = Field(ge=0)
    upper_pkr: float = Field(ge=0)


class WithheldForecast(Record):
    status: Literal['insufficient_history', 'quality_blocked']
    reason: str
    required_months: int = 30


class CashflowReport(Record):
    method_version: Literal['cashflow-local-v2'] = 'cashflow-local-v2'
    computed_at: datetime
    as_of_date: str
    source_sha256: str
    parser_version: str
    observations: int = Field(ge=3, le=120)
    first_month: str
    last_month: str
    series: list[Month]
    omitted_chart_months: int = Field(ge=0)
    trend_window_months: int = Field(ge=3, le=12)
    trend_slope_pkr_per_month: float
    recent_three_vs_previous_three_percent: float | None
    negative_net_months: int = Field(ge=0)
    unreadable_rows: int = Field(ge=0)
    quiet_months: list[str]
    warnings: list[str]
    forecast: ReadyForecast | WithheldForecast
    notes: list[str]
    source_quality: SourceQuality | None = None
