"""Finite, read-only ML diagnostics; none of these fields is an officer decision."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DiagnosticRecord(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class InputCheck(DiagnosticRecord):
    name: str
    label: str
    entered: float
    model_value: float
    training_lower: float
    training_upper: float
    clipped: bool
    transformation: str


class MemberPrediction(DiagnosticRecord):
    name: str
    label: str
    weight: float = Field(ge=0, le=1)
    raw_default_probability: float = Field(ge=0, le=1)
    score: float = Field(ge=0, le=100)


class MLScenario(DiagnosticRecord):
    loan_factor: float = Field(gt=0)
    receipts_factor: float = Field(gt=0)
    loan_amount_pkr: float = Field(gt=0)
    monthly_digital_payments: float = Field(ge=0)
    cash_flow_proxy: float = Field(ge=0)
    score: float = Field(ge=0, le=100)
    score_change: float
    recommendation: str | None = None
    recommendation_changed: bool | None = None


class InputApplicability(DiagnosticRecord):
    status: Literal['ready', 'unavailable']
    reason: str | None = None
    atypical: bool | None = None
    anomaly_score: float | None = None
    training_percentile: float | None = Field(default=None, ge=0, le=100)
    threshold: float | None = None
    flag_quantile: float | None = Field(default=None, gt=0, lt=1)
    artifact_sha256: str | None = None
    reference_sha256: str | None = None
    train_rows: int | None = None
    interpretation: str | None = None


class CaseDiagnostics(DiagnosticRecord):
    application_id: int
    status: Literal['ready', 'partial', 'unavailable']
    reason: str | None = None
    computed_at: datetime
    recorded_model_version: str | None = None
    serving_model_version: str
    credit_artifact_sha256: str | None = None
    stored_score: float
    recomputed_score: float | None = None
    source_verified: bool = False
    input_checks: list[InputCheck] = Field(default_factory=list)
    members: list[MemberPrediction] = Field(default_factory=list)
    member_spread_pp: float | None = None
    ensemble_raw_default_probability: float | None = None
    applicability: InputApplicability | None = None
    policy_note: str | None = None
    baseline_recommendation: str | None = None
    nearest_policy_boundary_distance: float | None = None
    scenarios: list[MLScenario] = Field(default_factory=list)
    scenario_note: str | None = None
    limitations: list[str] = Field(default_factory=list)


class ModelInputRequest(DiagnosticRecord):
    """Only the five figures used by the current three-feature model."""
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid', strict=True)

    loan_amount_pkr: float = Field(gt=0, le=500_000_000)
    monthly_digital_payments: float = Field(ge=0, le=1_000_000_000)
    cash_flow_proxy: float = Field(ge=0, le=1_000_000_000)
    payment_history_score: float = Field(ge=0, le=100)
    years_in_operation: float = Field(ge=0, le=100)


class ModelInputReport(DiagnosticRecord):
    status: Literal['ready', 'partial', 'unavailable']
    reason: str | None = None
    computed_at: datetime
    inputs: ModelInputRequest
    model_version: str
    credit_artifact_sha256: str | None = None
    input_checks: list[InputCheck] = Field(default_factory=list)
    applicability: InputApplicability | None = None
    notes: list[str] = Field(default_factory=list)
