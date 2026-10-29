"""Operational arithmetic, separate from credit inference and decisions."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OperatingFigures(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)
    loan_amount_pkr: float = Field(gt=0, le=500_000_000)
    tenure_months: int = Field(ge=3, le=84)
    monthly_digital_payments: float = Field(ge=0, le=1_000_000_000)
    cash_flow_proxy: float = Field(ge=0, le=1_000_000_000)
    existing_debt_pkr: float = Field(ge=0, le=1_000_000_000)
    inventory_turnover: float = Field(ge=0, le=50)
    order_consistency: float = Field(ge=0, le=100)
    num_employees: int = Field(ge=0, le=5000)


class OperatingRequest(OperatingFigures):
    statement_csv: str | None = Field(default=None, min_length=1, max_length=2_000_000)


class OperatingMetric(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    name: str
    label: str
    value: float | None
    unit: Literal['PKR', 'ratio', 'days', 'points']
    formula: str
    note: str


class OperatingReport(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    method: Literal['operating-arithmetic-v1'] = 'operating-arithmetic-v1'
    computed_at: datetime
    application_id: int | None = None
    inputs: OperatingFigures
    metrics: list[OperatingMetric]
    order_source: Literal['officer_entered', 'statement_receipts_proxy']
    receipt_consistency_reference: float | None = None
    statement_sha256: str | None = None
    statement_full_months: int | None = None
    notes: list[str]
