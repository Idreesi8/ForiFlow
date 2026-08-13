"""Pydantic request/response schemas for the ForiFlow API.

Every field carries an explicit range so that malformed underwriting data is
rejected at the edge rather than silently skewing a credit decision.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field


class Decision(StrEnum):
    """Credit decision bands mandated by the ForiFlow policy matrix."""

    REJECTED = "Rejected"
    MANUAL_REVIEW = "Manual Review"
    APPROVED = "Approved"


class RiskBand(StrEnum):
    """Human-readable risk grade attached to a score."""

    HIGH = "High Risk"
    MEDIUM = "Medium Risk"
    LOW = "Low Risk"


class AlertStatus(StrEnum):
    """Lifecycle of an EWS alert."""

    ACTIVE = "Active"
    IN_REVIEW = "In Review"
    RESOLVED = "Resolved"


class InstallmentStatus(StrEnum):
    """Repayment status for a monitored month, aligned with ECIB ageing buckets."""

    ON_TIME = "On Time"
    LATE_1_29 = "Late 1-29"
    LATE_30_59 = "Late 30-59"
    LATE_60_89 = "Late 60-89"
    DEFAULT = "Default"


class DataSource(StrEnum):
    """Dominant data feed behind a monthly EWS observation."""

    ECIB = "ECIB"
    POS = "POS"
    BANK_STATEMENT = "Bank Statement"
    SELF_REPORTED = "Self Reported"


class SMEApplicant(BaseModel):
    """Alternative-data feature set submitted for an SME credit assessment."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "applicant_name": "Ayesha Siddiqui",
                "business_name": "Siddiqui Textiles (Faisalabad)",
                "loan_amount_pkr": 2_500_000,
                "tenure_months": 24,
                "monthly_digital_payments": 1_450_000,
                "payment_history_score": 78,
                "inventory_turnover": 6.5,
                "order_consistency": 82,
                "existing_debt_pkr": 900_000,
                "cash_flow_proxy": 410_000,
                "years_in_operation": 7,
                "num_employees": 18,
            }
        },
    )

    applicant_name: str = Field(
        ..., min_length=2, max_length=120, description="Legal name of the applicant."
    )
    business_name: str = Field(
        ..., min_length=2, max_length=160, description="Registered business name."
    )
    loan_amount_pkr: float = Field(
        ..., gt=0, le=500_000_000, description="Requested facility amount in PKR."
    )
    tenure_months: int = Field(..., ge=3, le=84, description="Requested tenure in months.")
    monthly_digital_payments: float = Field(
        ...,
        ge=0,
        le=1_000_000_000,
        description="Average monthly digital receipts (Raast, POS, wallets) in PKR.",
    )
    payment_history_score: float = Field(
        ..., ge=0, le=100, description="Repayment behaviour score derived from ECIB history."
    )
    inventory_turnover: float = Field(
        ..., ge=0, le=50, description="Inventory turnover ratio (times per year)."
    )
    order_consistency: float = Field(
        ..., ge=0, le=100, description="Stability of order volumes over the last 12 months."
    )
    existing_debt_pkr: float = Field(
        ..., ge=0, le=1_000_000_000, description="Outstanding debt across all lenders in PKR."
    )
    cash_flow_proxy: float = Field(
        ..., ge=0, le=1_000_000_000, description="Estimated monthly net cash flow in PKR."
    )
    years_in_operation: float = Field(
        ..., ge=0, le=100, description="Years the business has been trading."
    )
    num_employees: int = Field(..., ge=0, le=5_000, description="Headcount including owners.")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def monthly_installment_pkr(self) -> float:
        """Straight-line monthly installment used for affordability checks."""
        return round(self.loan_amount_pkr / self.tenure_months, 2)


class ShapFeatureContribution(BaseModel):
    """Additive contribution of a single feature to the final score."""

    feature: str = Field(..., description="Machine-readable feature key.")
    label: str = Field(..., description="Credit-officer friendly feature name.")
    value: float = Field(..., description="Raw submitted feature value.")
    contribution: float = Field(
        ..., description="Signed score points added (+) or removed (-) by this feature."
    )
    direction: str = Field(..., description="'increases' or 'decreases' the score.")
    weight: float = Field(..., description="Relative model weight of the feature (0-1).")


class ExplanationResponse(BaseModel):
    """SHAP-style explanation for one scored application."""

    application_id: int
    business_name: str
    risk_score: float
    decision: Decision
    risk_band: RiskBand
    base_value: float = Field(..., description="Portfolio average score before features apply.")
    feature_contributions: list[ShapFeatureContribution]
    top_positive_factors: list[str]
    top_negative_factors: list[str]
    narrative: str = Field(..., description="Adverse-action style summary for the credit file.")
    compliance_note: str
    model_version: str | None = Field(
        default=None, description="Engine that produced this explanation, for audit trails."
    )


class ScoreResponse(BaseModel):
    """Result of a credit assessment."""

    application_id: int
    applicant_name: str
    business_name: str
    loan_amount_pkr: float
    tenure_months: int
    monthly_installment_pkr: float
    risk_score: float = Field(..., ge=0, le=100, description="0 = worst, 100 = best.")
    decision: Decision
    risk_band: RiskBand
    confidence: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description=(
            "Decision stability indicator: ensemble agreement combined with the "
            "score's distance from the nearest policy boundary. Not a statistical "
            "confidence interval, and absent for the surrogate engine."
        ),
    )
    model_version: str | None = Field(
        default=None, description="Scoring engine that produced this decision."
    )
    explanation: ExplanationResponse | None = None
    created_at: datetime


class ApplicationSummary(BaseModel):
    """Compact application record for dashboard tables."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    applicant_name: str
    business_name: str
    loan_amount_pkr: float
    tenure_months: int
    risk_score: float
    decision: Decision
    created_at: datetime


class EWSMonitorRequest(BaseModel):
    """One month of post-disbursement surveillance data for a borrower."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "borrower_id": 1,
                "month_number": 4,
                "installment_status": "Late 30-59",
                "bureau_balance": 1_650_000,
                "pos_cash_balance": 240_000,
                "data_source_primary": "ECIB",
            }
        },
    )

    borrower_id: int = Field(..., gt=0, description="Application id of the borrower.")
    month_number: int = Field(..., ge=1, le=84, description="Months since disbursement.")
    installment_status: InstallmentStatus
    bureau_balance: float = Field(
        ..., ge=0, le=1_000_000_000, description="Outstanding balance per ECIB, in PKR."
    )
    pos_cash_balance: float = Field(
        ..., ge=0, le=1_000_000_000, description="Monthly POS settlement inflow in PKR."
    )
    data_source_primary: DataSource = DataSource.ECIB
    current_score: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Externally computed score. Derived from the payload when omitted.",
    )


class AlertResponse(BaseModel):
    """An EWS alert as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    borrower_id: int
    baseline_score: float
    current_score: float
    score_drop: float
    estimated_days_to_default: int
    alert_status: AlertStatus
    triggered_at: datetime
    resolved_at: datetime | None = None


class EWSTrackingResponse(BaseModel):
    """A stored monthly EWS observation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    borrower_id: int
    month_number: int
    installment_status: InstallmentStatus
    bureau_balance: float
    pos_cash_balance: float
    monthly_score: float
    data_source_primary: DataSource


class EWSMonitorResponse(BaseModel):
    """Outcome of a monitoring run for a single borrower-month."""

    borrower_id: int
    business_name: str
    month_number: int
    baseline_score: float
    current_score: float
    score_drop: float
    alert_triggered: bool
    alert_threshold: float
    estimated_days_to_default: int | None = None
    recommended_action: str
    tracking: EWSTrackingResponse
    alert: AlertResponse | None = None


class HealthResponse(BaseModel):
    """Liveness payload."""

    status: str
    service: str
    version: str
    database: str
