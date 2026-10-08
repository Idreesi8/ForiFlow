"""Pydantic request/response schemas for the ForiFlow API.

Every field carries an explicit range so that malformed underwriting data is
rejected at the edge rather than silently skewing a credit decision.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class Decision(StrEnum):
    """The policy recommendation, in the vocabulary stored since release 1.0.

    The values read like outcomes but are recommendations: ``Approved`` means
    "the policy recommends approval". See :class:`Recommendation` for the same
    three values worded as recommendations, and :class:`DecisionStatus` for
    what an officer actually decided.
    """

    REJECTED = "Rejected"
    MANUAL_REVIEW = "Manual Review"
    APPROVED = "Approved"


class OfficerDecision(StrEnum):
    """An authorised officer's final decision on an application."""

    APPROVED = "Approved"
    REJECTED = "Rejected"


class OfficerAction(StrEnum):
    """What an officer may record: a final decision, or passing it upward."""

    APPROVED = "Approved"
    REJECTED = "Rejected"
    ESCALATED = "Escalated"


class Recommendation(StrEnum):
    """What the policy recommends for a score. Never a final decision."""

    APPROVE = "Approve"
    MANUAL_REVIEW = "Manual Review"
    DECLINE = "Decline"


class DecisionStatus(StrEnum):
    """Where an application stands with the people who decide it."""

    PENDING = "Pending"
    ESCALATED = "Escalated"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    SUPERSEDED = "Superseded"


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
    """Repayment status for a monitored month.

    Labels follow ECIB-style ageing buckets. Values are officer-entered;
    they are not pulled from a live bureau.
    """

    ON_TIME = "On Time"
    LATE_1_29 = "Late 1-29"
    LATE_30_59 = "Late 30-59"
    LATE_60_89 = "Late 60-89"
    DEFAULT = "Default"


class BusinessSector(StrEnum):
    """Line of business, used only for portfolio concentration reporting.

    The model does not read it: the public training data has no sector column.
    """

    RETAIL = "Retail"
    WHOLESALE = "Wholesale & Trading"
    MANUFACTURING = "Manufacturing"
    TEXTILE = "Textile & Garments"
    FOOD = "Food & Hospitality"
    AGRICULTURE = "Agriculture & Livestock"
    SERVICES = "Services"
    TRANSPORT = "Transport & Logistics"
    CONSTRUCTION = "Construction"
    OTHER = "Other"


class DataSource(StrEnum):
    """Officer-selected label for which typed source dominated the month.

    ``ECIB`` means the officer keyed figures from a bureau extract. It is not
    a live connector.
    """

    ECIB = "ECIB"
    POS = "POS"
    BANK_STATEMENT = "Bank Statement"
    SELF_REPORTED = "Self Reported"


class IdentifierType(StrEnum):
    """What a borrower's national identifier is."""

    CNIC = "CNIC"
    NTN = "NTN"


class BorrowerStatus(StrEnum):
    """Whether new applications may be opened for a borrower."""

    ACTIVE = "active"
    INACTIVE = "inactive"


# Digits a valid identifier has once dashes and spaces are removed: a CNIC is
# 13; an NTN is 7, or 8 with its check digit.
IDENTIFIER_DIGITS: dict[IdentifierType, tuple[int, ...]] = {
    IdentifierType.CNIC: (13,),
    IdentifierType.NTN: (7, 8),
}


def normalise_identifier(kind: IdentifierType, value: str) -> str:
    """Return a CNIC or NTN as digits only, or raise ``ValueError``."""
    digits = re.sub(r"[\s-]", "", value)
    allowed = IDENTIFIER_DIGITS[kind]
    if not digits.isdigit() or len(digits) not in allowed:
        raise ValueError(
            f"A {kind.value} has {' or '.join(str(n) for n in allowed)} digits "
            "(dashes and spaces are ignored)."
        )
    return digits


class _IdentifierPair(BaseModel):
    """Shared rule: an identifier and its type come together, normalised."""

    borrower_identifier_type: IdentifierType | None = Field(
        default=None, description="'CNIC' (owner) or 'NTN' (business)."
    )
    borrower_identifier: str | None = Field(
        default=None,
        max_length=24,
        description=(
            "The CNIC (13 digits) or NTN (7 or 8 digits). Dashes and spaces are "
            "ignored. Optional. Stored once per borrower; never read by the model."
        ),
    )

    @model_validator(mode="after")
    def _identifier_comes_with_its_type(self) -> Any:
        kind, value = self.borrower_identifier_type, self.borrower_identifier
        if (kind is None) != (value is None or value.strip() == ""):
            raise ValueError(
                "borrower_identifier and borrower_identifier_type must be given together."
            )
        if kind is not None and value is not None:
            self.borrower_identifier = normalise_identifier(kind, value)
        else:
            self.borrower_identifier = None
        return self


class SMEApplicant(_IdentifierPair):
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
        ...,
        ge=0,
        le=100,
        description=(
            "Officer-entered repayment score on a 0–100 ECIB-oriented scale. "
            "Not pulled from a live bureau."
        ),
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
    business_sector: BusinessSector | None = Field(
        default=None,
        description="Line of business. Used for portfolio reporting, not by the model.",
    )
    contact_phone: str | None = Field(
        default=None,
        pattern=r"^\+?[0-9]{10,15}$",
        description=(
            "Borrower's mobile number, digits only with an optional leading +, "
            "e.g. +923001234567. Used for payment reminders, not by the model."
        ),
    )
    borrower_public_id: str | None = Field(
        default=None,
        pattern=r"^BRW-[0-9]{6,}$",
        description=(
            "Reference of an existing borrower, e.g. BRW-000012, to file this "
            "application under. Omit it for a business not yet on file: a "
            "borrower record is then created (or found by identifier)."
        ),
    )
    rescore_of_application_id: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Re-assess this undecided application with the figures sent here. A new "
            "application is stored; the earlier one is kept unchanged and marked "
            "Superseded."
        ),
    )
    statement_csv: str | None = Field(
        default=None,
        max_length=2_000_000,
        description=(
            "The wallet or bank statement the turnover figures were taken from, as "
            "CSV text. The API re-reads it and stores a summary as evidence; the "
            "raw transactions are not kept."
        ),
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def monthly_installment_pkr(self) -> float:
        """Straight-line monthly installment used for affordability checks."""
        return round(self.loan_amount_pkr / self.tenure_months, 2)


class UserRole(StrEnum):
    """On-premise officer roles, highest first.

    Everyone scores, monitors and takes alerts for review. A manager also
    decides Manual Review cases and resolves EWS alerts. An admin does all of
    that and manages officer accounts."""

    ADMIN = "admin"
    MANAGER = "manager"
    ANALYST = "analyst"


RECOMMENDATION_OF: dict[Decision, Recommendation] = {
    Decision.APPROVED: Recommendation.APPROVE,
    Decision.MANUAL_REVIEW: Recommendation.MANUAL_REVIEW,
    Decision.REJECTED: Recommendation.DECLINE,
}


class ReasonCode(BaseModel):
    """One coded risk factor, derived from the SHAP explanation."""

    code: str = Field(..., description="Stable code, e.g. R02.")
    label: str = Field(..., description="What the code means, in plain words.")
    feature: str = Field(..., description="The explanation feature it comes from.")
    points: float = Field(..., description="Score points this factor took away (negative).")


class ModelAssessment(BaseModel):
    """What the model said. No recommendation and no decision."""

    model_config = ConfigDict(protected_namespaces=())

    risk_score: float = Field(..., description="0 = worst, 100 = best.")
    risk_band: RiskBand | None = Field(
        default=None, description="Where the score falls under the policy's cut-offs."
    )
    probability_of_default_raw: float | None = Field(
        default=None,
        description=(
            "The model's own probability (0-1). It is trained on balanced data, so "
            "it ranks applicants well but runs high. Null for the fallback formula "
            "and for applications scored before it was stored."
        ),
    )
    probability_of_default: float | None = Field(
        default=None, description="The calibrated probability of default (0-1)."
    )
    model_version: str | None = None
    scoring_engine: str | None = None


class ApprovalAuthority(BaseModel):
    """Who may approve this application, and why."""

    approve_requires: UserRole = Field(
        ..., description="The lowest role that may approve: manager or admin."
    )
    manager_approval_limit_pkr: float
    reason: str = Field(
        ...,
        description=(
            "'within_manager_limit', 'above_manager_limit', "
            "'approval_against_decline_recommendation' or 'escalated'."
        ),
    )


class PolicyBands(BaseModel):
    """The score cut-offs that applied to an assessment: what a dial should draw."""

    decline_max_score: float = Field(..., description="At or below: recommend Decline (High Risk).")
    manual_review_max_score: float = Field(
        ..., description="Above decline_max and at or below this: Manual Review (Medium Risk)."
    )
    approve_above_score: float = Field(..., description="Above this: recommend Approve (Low Risk).")
    source: str = Field(
        ...,
        description=(
            "'policy_snapshot': stored with the application at scoring time. "
            "'active_policy': the policy in force now. 'legacy_fixed_rule': the fixed "
            "40 / 70 cut-offs in the code before 2.0, for applications scored then."
        ),
    )


class PolicyRecommendation(BaseModel):
    """What the credit policy recommends for the assessment. Not a decision."""

    recommendation: Recommendation
    policy_id: int | None = None
    policy_version: str | None = Field(
        default=None,
        description="Null when the application was scored before policy versions were recorded.",
    )
    policy_name: str | None = None
    triggered_rules: list[dict] = Field(
        default_factory=list, description="The threshold rule(s) the score met."
    )
    reason: str = Field(..., description="The recommendation in one sentence.")
    authority: ApprovalAuthority
    bands: PolicyBands | None = Field(
        default=None, description="The cut-offs this recommendation was made under."
    )


class OfficerDecisionRecord(BaseModel):
    """The human decision, or that none has been made yet."""

    status: DecisionStatus
    decision: OfficerDecision | None = Field(
        default=None, description="Approved or Rejected once decided; null before."
    )
    decided_by: str | None = None
    decided_at: datetime | None = None
    note: str | None = None
    source: str | None = Field(
        default=None,
        description=(
            "'officer': a named officer decided. 'legacy_auto': decided by the "
            "score band alone under the pre-2.0 rule; no officer was recorded."
        ),
    )
    overrides_recommendation: bool | None = Field(
        default=None,
        description="True when the officer decided against the recommendation.",
    )
    escalated_by: str | None = None
    escalated_at: datetime | None = None
    escalation_note: str | None = None
    superseded_by_application_id: int | None = None


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


class ApprovalStep(BaseModel):
    """What would move this application into a better policy band."""

    target_decision: Decision
    max_loan_pkr: float | None = Field(
        default=None,
        description=(
            "Largest facility, rounded down to PKR 1,000, at which this applicant "
            "reaches the target band with everything else unchanged. Null when no "
            "facility size reaches it."
        ),
    )
    score_at_max_loan: float | None = None
    required_monthly_turnover_pkr: float | None = Field(
        default=None,
        description=(
            "Smallest documented monthly turnover, rounded up to PKR 1,000, at "
            "which the requested facility reaches the target band. Null when no "
            "turnover reaches it."
        ),
    )
    score_at_turnover: float | None = None


class ApprovalPath(BaseModel):
    """Exact routes to a better decision, found by searching the monotone model.

    The model can only score a smaller facility, or a higher turnover, the same
    or better, so each threshold is unique. These are model outputs for the
    officer, not an offer: a higher turnover has to be evidenced.
    """

    requested_loan_pkr: float
    monthly_turnover_pkr: float
    steps: list[ApprovalStep]
    blocked_by: list[str] = Field(
        default_factory=list,
        description="Factors that keep a step out of reach whatever the facility size.",
    )


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
    recommendation: Recommendation | None = Field(
        default=None,
        description="``decision`` worded as what it is: the policy's recommendation.",
    )
    policy_version: str | None = Field(
        default=None, description="Policy version whose cut-offs labelled this score."
    )
    reason_codes: list[ReasonCode] = Field(
        default_factory=list,
        description="The largest risk factors as stable codes, derived from the contributions.",
    )
    approval_path: ApprovalPath | None = Field(
        default=None,
        description=(
            "For a Decline or Manual Review recommendation from the trained ensemble: "
            "the facility size and the turnover at which the same applicant reaches the "
            "next bands. Absent for an Approve recommendation and for the surrogate engine."
        ),
    )
    probability_of_default: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Calibrated probability of default (0-1): isotonic regression on "
            "out-of-fold predictions, calibrated to the default rate of the public "
            "training file, not of a Pakistani SME portfolio. The score and bands "
            "stay on the raw model. Absent for the surrogate engine and for "
            "explanations stored before 1.4.0."
        ),
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
        default=None, description="Model version that produced this score. Stored with it."
    )
    scoring_engine: str | None = Field(
        default=None,
        description=(
            "'ml': the trained ensemble. 'surrogate': the hand-weighted fallback "
            "formula, which serves only when pinned or when the trained model "
            "could not be loaded."
        ),
    )
    borrower_id: int | None = Field(default=None, description="The borrower this is filed under.")
    borrower_public_id: str | None = Field(default=None, description="e.g. BRW-000012.")
    borrower_created: bool = Field(
        default=False, description="True when this application opened a new borrower record."
    )
    probability_of_default: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Calibrated probability of default (0-1). See ExplanationResponse.",
    )
    recommendation: Recommendation | None = Field(
        default=None, description="The policy's recommendation. Not a decision."
    )
    policy_version: str | None = None
    decision_status: DecisionStatus = Field(
        default=DecisionStatus.PENDING,
        description="Always Pending on a new assessment: an officer has not decided yet.",
    )
    assessment: ModelAssessment | None = None
    policy: PolicyRecommendation | None = None
    officer_decision: OfficerDecisionRecord | None = None
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    supersedes_application_id: int | None = Field(
        default=None, description="The earlier assessment this one replaced, if it is a re-score."
    )
    explanation: ExplanationResponse | None = None
    created_at: datetime
    scored_by: str | None = Field(default=None, description="Officer who ran the assessment.")


def _bands_of(policy_evaluation: dict) -> PolicyBands:
    """The cut-offs an application was assessed under.

    From its stored policy snapshot; for an application scored before 2.0,
    which has none, the fixed cut-offs the code used then. Never the policy in
    force today, so activating a new policy does not redraw old assessments.
    """
    stored = policy_evaluation.get("bands")
    if stored:
        low, high = float(stored["decline_max_score"]), float(stored["manual_review_max_score"])
        source = "policy_snapshot"
    else:
        from services.policy_rules import (
            LEGACY_DECLINE_MAX_SCORE,
            LEGACY_MANUAL_REVIEW_MAX_SCORE,
        )

        low, high = LEGACY_DECLINE_MAX_SCORE, LEGACY_MANUAL_REVIEW_MAX_SCORE
        source = "legacy_fixed_rule"
    return PolicyBands(
        decline_max_score=low, manual_review_max_score=high, approve_above_score=high, source=source
    )


class ApplicationSummary(BaseModel):
    """An application: the model's assessment, the policy's recommendation and
    the officer's decision, kept apart.

    ``decision`` is the recommendation in the vocabulary stored since 1.0
    (``Approved`` = recommend approve); ``recommendation`` is the same value
    worded as a recommendation. Neither is a decision. ``decision_status`` and
    ``final_decision`` say what an officer decided; ``final_decision`` is
    ``None`` until one has.
    """

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    borrower_id: int | None = Field(
        default=None, description="The business this application belongs to."
    )
    borrower_public_id: str | None = Field(default=None, description="e.g. BRW-000012.")
    applicant_name: str
    business_name: str
    loan_amount_pkr: float
    tenure_months: int
    risk_score: float
    risk_band: RiskBand | None = None
    raw_pd: float | None = Field(default=None, exclude=True)
    calibrated_pd: float | None = Field(default=None, exclude=True)
    decision: Decision = Field(
        ..., description="The policy recommendation, legacy wording. Not a final decision."
    )
    model_version: str | None = Field(
        default=None,
        description="Model version that produced the score. Null if scored before it was recorded.",
    )
    scoring_engine: str | None = Field(
        default=None, description="'ml' (trained ensemble) or 'surrogate' (fallback formula)."
    )
    policy_id: int | None = None
    policy_version: str | None = Field(
        default=None,
        description="Policy version the recommendation was made under. Null if never recorded.",
    )
    policy_evaluation: dict | None = Field(default=None, exclude=True)
    authority_view: dict = Field(default_factory=dict, exclude=True)
    reason_codes: list[ReasonCode] | None = None
    decision_status: DecisionStatus = DecisionStatus.PENDING
    decision_source: str | None = None
    escalated_by: str | None = None
    escalated_at: datetime | None = None
    escalation_note: str | None = None
    supersedes_application_id: int | None = None
    superseded_by_application_id: int | None = None
    created_at: datetime
    business_sector: str | None = None
    contact_phone: str | None = None
    turnover_evidence: dict | None = Field(
        default=None,
        description=(
            "Summary of the statement the turnover was taken from, with "
            "'matches_statement' saying whether the scored figures equal it. "
            "Null when the officer typed the turnover."
        ),
    )
    scored_by: str | None = None
    review_decision: OfficerDecision | None = None
    review_note: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recommendation(self) -> Recommendation:
        """The policy recommendation, worded as a recommendation."""
        return RECOMMENDATION_OF[self.decision]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def final_decision(self) -> Decision | None:
        """What an officer decided: Approved, Rejected, or None while undecided."""
        if self.decision_status is DecisionStatus.APPROVED:
            return Decision.APPROVED
        if self.decision_status is DecisionStatus.REJECTED:
            return Decision.REJECTED
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def manager_approval_limit_pkr(self) -> float:
        """Largest facility a manager may approve alone, under this application's policy."""
        return float(self.authority_view.get("manager_approval_limit_pkr", 0.0))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def approval_authority(self) -> UserRole:
        """The lowest role that may approve this application now."""
        return UserRole(self.authority_view.get("approve_requires", UserRole.ADMIN.value))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assessment(self) -> ModelAssessment:
        """The model's output, on its own."""
        return ModelAssessment(
            risk_score=self.risk_score,
            risk_band=self.risk_band,
            probability_of_default_raw=self.raw_pd,
            probability_of_default=self.calibrated_pd,
            model_version=self.model_version,
            scoring_engine=self.scoring_engine,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def policy(self) -> PolicyRecommendation:
        """The policy's recommendation and who may approve."""
        stored = self.policy_evaluation or {}
        return PolicyRecommendation(
            recommendation=self.recommendation,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            policy_name=stored.get("policy_name"),
            triggered_rules=stored.get("triggered_rules", []),
            reason=stored.get(
                "reason",
                f"Recommendation: {self.recommendation.value}. Scored before policy "
                "versions were recorded, so no policy version is on file.",
            ),
            authority=ApprovalAuthority(
                approve_requires=self.approval_authority,
                manager_approval_limit_pkr=self.manager_approval_limit_pkr,
                reason=self.authority_view.get("reason", "unknown"),
            ),
            bands=_bands_of(stored),
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def officer_decision(self) -> OfficerDecisionRecord:
        """The human decision, or that it is still open."""
        overrides: bool | None = None
        if self.review_decision is not None and self.decision is not Decision.MANUAL_REVIEW:
            overrides = self.review_decision.value != self.decision.value
        return OfficerDecisionRecord(
            status=self.decision_status,
            decision=(
                OfficerDecision(self.final_decision.value) if self.final_decision else None
            ),
            decided_by=self.reviewed_by,
            decided_at=self.reviewed_at,
            note=self.review_note,
            source=self.decision_source,
            overrides_recommendation=overrides,
            escalated_by=self.escalated_by,
            escalated_at=self.escalated_at,
            escalation_note=self.escalation_note,
            superseded_by_application_id=self.superseded_by_application_id,
        )


class StatementRequest(BaseModel):
    """A wallet or bank statement to summarise."""

    csv: str = Field(..., min_length=1, max_length=2_000_000, description="CSV text.")


class Reminder(BaseModel):
    """A payment reminder an officer can send to a borrower."""

    application_id: int
    business_name: str
    applicant_name: str
    contact_phone: str | None
    kind: str = Field(..., description="'overdue', 'due_soon' or 'arrears'.")
    installment_number: int | None = Field(
        ..., description="The next installment not yet recorded; null once all are."
    )
    installment_pkr: float
    due_date: date | None
    days_until_due: int | None = Field(..., description="Negative when past due.")
    arrears_pkr: float = Field(..., description="Due but unpaid in recorded months.")
    latest_status: InstallmentStatus | None
    message_en: str
    message_ur: str = Field(..., description="The same reminder in Roman Urdu.")


class ScoreBucket(BaseModel):
    """One bar of the score histogram: scores in (lower, upper], 0 included."""

    label: str
    lower: float
    upper: float
    count: int
    risk_band: RiskBand | None = Field(
        default=None, description="The band this bar lies in under the histogram's policy."
    )
    recommendation: Recommendation | None = Field(
        default=None, description="What that band recommends under the histogram's policy."
    )


class PortfolioStats(BaseModel):
    """Portfolio totals computed in SQL over every application and alert."""

    total_applications: int
    superseded_assessments: int = Field(
        default=0,
        description="Earlier assessments replaced by a re-score. Kept, but not counted above.",
    )
    model_decisions: dict[str, int] = Field(
        ...,
        description=(
            "Applications per policy recommendation, legacy wording "
            "(Approved / Manual Review / Rejected). Recommendations, not decisions."
        ),
    )
    recommendations: dict[str, int] = Field(
        default_factory=dict,
        description="The same counts worded as recommendations (Approve / Manual Review / Decline).",
    )
    pending_review: int = Field(
        ..., description="Applications awaiting an officer decision (Pending or Escalated)."
    )
    final_approved: int = Field(..., description="Applications approved by an officer.")
    final_rejected: int = Field(..., description="Applications rejected by an officer.")
    approval_rate: float = Field(..., description="final_approved / total, in percent.")
    approved_exposure_pkr: float
    average_score: float | None
    score_histogram: list[ScoreBucket]
    histogram_policy_version: str | None = Field(
        default=None,
        description=(
            "The bars are cut on this (active) policy's cut-offs. Each application "
            "keeps the recommendation it was given under its own policy."
        ),
    )
    histogram_bands: PolicyBands | None = None
    open_alerts: int = Field(..., description="EWS alerts that are Active or In Review.")
    worst_open_drop: float | None


class ReviewRequest(BaseModel):
    """An officer's decision on an application: approve, reject or escalate."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "decision": "Approved",
                "note": "Five years of clean POS receipts; facility is 28% of turnover.",
            }
        },
    )

    decision: OfficerAction
    note: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Why the officer approved, rejected or escalated it. Kept on the credit file.",
    )


class AlertResolveRequest(BaseModel):
    """How an EWS alert was closed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    note: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="What was done, e.g. 'Borrower paid arrears on 12 Oct'.",
    )


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
        ...,
        ge=0,
        le=1_000_000_000,
        description=(
            "Officer-entered outstanding balance in PKR. Not connected to a live ECIB feed."
        ),
    )
    pos_cash_balance: float = Field(
        ..., ge=0, le=1_000_000_000, description="Monthly POS settlement inflow in PKR."
    )
    data_source_primary: DataSource = DataSource.ECIB
    amount_paid_pkr: float | None = Field(
        default=None,
        ge=0,
        le=1_000_000_000,
        description=(
            "What the borrower paid this month in PKR. Optional; months without it "
            "are left out of the collection figures."
        ),
    )
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
    business_name: str | None = None
    baseline_score: float
    current_score: float
    score_drop: float
    estimated_days_to_default: int
    alert_status: AlertStatus
    triggered_at: datetime
    resolved_at: datetime | None = None
    assigned_to: str | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None


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
    amount_paid_pkr: float | None = None


class StatusExposure(BaseModel):
    """Monitored facilities whose latest month shows this repayment status."""

    status: InstallmentStatus
    facilities: int
    outstanding_pkr: float


class DecisionMatrixRow(BaseModel):
    """What officers decided on the applications given one recommendation."""

    model_decision: Decision = Field(
        ..., description="The policy recommendation, legacy wording. Not a decision."
    )
    approved: int
    rejected: int
    pending: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recommendation(self) -> Recommendation:
        """The same band worded as a recommendation."""
        return RECOMMENDATION_OF[self.model_decision]


class SectorRow(BaseModel):
    """Portfolio concentration for one line of business."""

    sector: str
    applications: int
    approved: int
    approval_rate: float = Field(..., description="approved / applications, in percent.")
    approved_exposure_pkr: float
    average_score: float
    overdue_pkr: float
    open_alerts: int


class PortfolioSummary(BaseModel):
    """Repayment position of the approved book, from officer-recorded months.

    Installments are straight-line (facility / tenure): ForiFlow holds no
    interest rate. Collection figures cover only months where the officer
    recorded an amount; ``months_without_amount`` says how many did not.
    """

    approved_facilities: int
    monitored_facilities: int
    disbursed_pkr: float = Field(..., description="Sum of approved facility amounts.")
    due_pkr: float = Field(..., description="Installments due in months with an amount.")
    collected_pkr: float
    collection_rate: float | None = Field(
        ..., description="collected / due, in percent. Null when nothing is due yet."
    )
    overdue_pkr: float = Field(
        ..., description="Per facility, due minus collected where that is positive."
    )
    outstanding_pkr: float = Field(..., description="Approved amounts not yet collected.")
    defaulted_facilities: int = Field(..., description="Latest month recorded as Default.")
    defaulted_outstanding_pkr: float
    par30: float | None = Field(
        ...,
        description=(
            "Portfolio at risk: outstanding on monitored facilities 30 or more days "
            "late in their latest month, over outstanding on all monitored "
            "facilities, in percent. Null when nothing is monitored."
        ),
    )
    months_with_amount: int
    months_without_amount: int
    latest_status: list[StatusExposure]
    decision_matrix: list[DecisionMatrixRow]
    sectors: list[SectorRow]


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
    default_probability_3m: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Probability of reaching Default within three months, from a Markov "
            "chain fitted on monthly repayment histories of consumer card accounts "
            "(UCI, Taiwan 2005), not on SME loans. Null when no chain is loaded."
        ),
    )
    runway_basis: str = Field(
        default="rules",
        description=(
            "'markov': estimated_days_to_default is the chain's mean time to "
            "Default given it happens within 12 months. 'rules': the heuristic."
        ),
    )
    recommended_action: str
    tracking: EWSTrackingResponse
    alert: AlertResponse | None = None


class HealthResponse(BaseModel):
    """Liveness payload."""

    status: str
    service: str
    version: str
    database: str
    scoring_engine: str | None = Field(
        default=None, description="'ml' or 'surrogate': the engine scoring right now."
    )
    model_version: str | None = None
    scoring_fallback_reason: str | None = Field(
        default=None,
        description=(
            "Set when the fallback formula is serving: 'pinned', "
            "'artifacts_missing' or 'load_failed'."
        ),
    )


class LoginRequest(BaseModel):
    """Credentials for ``POST /auth/login``."""

    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=72)


class UserCreate(BaseModel):
    """New officer account for ``POST /auth/users`` (admin only)."""

    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    # 12 is MIN_PASSWORD_LENGTH in services.auth_service; 72 is bcrypt's limit.
    password: str = Field(..., min_length=12, max_length=72)
    role: UserRole = UserRole.ANALYST


class UserResponse(BaseModel):
    """An officer account. The password hash is never returned."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: UserRole
    created_at: datetime


class TokenResponse(BaseModel):
    """JWT issued after a successful login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
    role: UserRole


class BorrowerCreate(_IdentifierPair):
    """A new borrower record for ``POST /borrowers``."""

    business_name: str = Field(..., min_length=2, max_length=160)
    owner_name: str = Field(..., min_length=2, max_length=120)
    contact_phone: str | None = Field(default=None, pattern=r"^\+?[0-9]{10,15}$")
    business_sector: BusinessSector | None = None
    years_in_operation: float | None = Field(default=None, ge=0, le=100)


class BorrowerUpdate(_IdentifierPair):
    """Fields a manager may correct on a borrower. Omitted fields are kept."""

    business_name: str | None = Field(default=None, min_length=2, max_length=160)
    owner_name: str | None = Field(default=None, min_length=2, max_length=120)
    contact_phone: str | None = Field(default=None, pattern=r"^\+?[0-9]{10,15}$")
    business_sector: BusinessSector | None = None
    years_in_operation: float | None = Field(default=None, ge=0, le=100)
    status: BorrowerStatus | None = None


class BorrowerResponse(BaseModel):
    """A borrower. The identifier is returned masked."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    public_id: str
    business_name: str
    owner_name: str
    identifier_type: IdentifierType | None = None
    identifier_masked: str | None = Field(
        default=None, description="CNIC or NTN with all but the last four digits hidden."
    )
    contact_phone: str | None = None
    business_sector: str | None = None
    years_in_operation: float | None = None
    status: BorrowerStatus
    created_at: datetime
    updated_at: datetime


class BorrowerApplicationHistory(BaseModel):
    """One application in a borrower's history, with its monitoring and alerts."""

    application_id: int
    created_at: datetime
    loan_amount_pkr: float
    tenure_months: int
    risk_score: float
    decision: Decision = Field(
        ..., description="The policy recommendation at scoring time, legacy wording."
    )
    recommendation: Recommendation | None = None
    policy_version: str | None = None
    decision_status: DecisionStatus = DecisionStatus.PENDING
    final_decision: Decision | None = Field(
        ..., description="The officer's decision; null while none has been made."
    )
    review_decision: OfficerDecision | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    scored_by: str | None = None
    model_version: str | None = None
    scoring_engine: str | None = None
    monitoring: list[EWSTrackingResponse]
    alerts: list[AlertResponse]


class BorrowerHistorySummary(BaseModel):
    """The borrower's record at a glance."""

    applications: int
    first_application_at: datetime | None
    latest_application_at: datetime | None
    latest_score: float | None
    lowest_score: float | None
    highest_score: float | None
    approved_facilities: int
    monitored_months: int
    open_alerts: int
    total_alerts: int
    model_versions_used: list[str]
    scoring_engines_used: list[str]
    policy_versions_used: list[str] = Field(default_factory=list)


class BorrowerHistory(BaseModel):
    """Everything on file for one borrower, oldest application first."""

    borrower: BorrowerResponse
    summary: BorrowerHistorySummary
    applications: list[BorrowerApplicationHistory]


class ModelVersionResponse(BaseModel):
    """A scoring model that has served decisions from this database."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    version: str
    engine: str
    artifact_sha256: str
    training_dataset: str | None = None
    feature_set: list[str] | None = None
    feature_set_version: str | None = None
    trained_at: str | None = None
    metrics: dict | None = None
    status: str
    is_active: bool
    fallback_reason: str | None = None
    registered_at: datetime
    applications_scored: int = Field(default=0, description="Applications this model scored.")


class AuditLogResponse(BaseModel):
    """One entry of the append-only audit trail."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    user_id: int | None = None
    username: str
    role: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    previous_state: dict | None = None
    new_state: dict | None = None
    details: dict | None = None
    ip_address: str | None = None
    request_id: str | None = None


class PolicyCreate(BaseModel):
    """A new policy version for ``POST /policy/versions`` (admin). Created as a draft."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "version": "1.1",
                "name": "Demo Credit Policy",
                "description": "Tighter manual-review band for the pilot.",
                "decline_max_score": 45,
                "manual_review_max_score": 75,
                "manager_approval_limit_pkr": 1_500_000,
                "decline_override_admin_only": True,
            }
        },
    )

    version: str = Field(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    name: str = Field(..., min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    decline_max_score: float = Field(
        ..., ge=0, lt=100, description="Score at or below this: recommend Decline."
    )
    manual_review_max_score: float = Field(
        ...,
        gt=0,
        le=100,
        description="Score above decline_max and at or below this: recommend Manual Review.",
    )
    manager_approval_limit_pkr: float = Field(..., ge=0, le=500_000_000)
    decline_override_admin_only: bool = Field(
        default=True,
        description="Only an admin may approve against a Decline recommendation.",
    )

    @model_validator(mode="after")
    def _bands_in_order(self) -> Any:
        if self.decline_max_score >= self.manual_review_max_score:
            raise ValueError("decline_max_score must be below manual_review_max_score.")
        return self


class PolicyResponse(BaseModel):
    """One version of the credit policy."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    version: str
    name: str
    description: str | None = None
    status: str
    is_active: bool
    decline_max_score: float
    manual_review_max_score: float
    approve_above_score: float
    manager_approval_limit_pkr: float
    decline_override_admin_only: bool
    created_at: datetime
    created_by: str
    activated_at: datetime | None = None
    activated_by: str | None = None
    retired_at: datetime | None = None
    applications_assessed: int = Field(
        default=0, description="Applications assessed under this version."
    )
    notice: str = Field(
        default=(
            "Configurable policy. The cut-offs are set by the lender; the shipped "
            "values are demo figures, not thresholds validated for Pakistani SME lending."
        )
    )


class AssessmentRecord(BaseModel):
    """One assessment in an application's history (the application or one it replaced)."""

    model_config = ConfigDict(protected_namespaces=())

    application_id: int
    created_at: datetime
    scored_by: str | None = None
    loan_amount_pkr: float
    risk_score: float
    risk_band: RiskBand | None = None
    recommendation: Recommendation
    model_version: str | None = None
    scoring_engine: str | None = None
    policy_version: str | None = None
    decision_status: DecisionStatus
    decided_by: str | None = None
    decided_at: datetime | None = None
    supersedes_application_id: int | None = None
    superseded_by_application_id: int | None = None


class DecisionEvent(BaseModel):
    """One recorded event in an application's decision history."""

    occurred_at: datetime
    application_id: int
    action: str
    actor: str
    role: str | None = None
    previous_state: dict | None = None
    new_state: dict | None = None
    details: dict | None = None
    request_id: str | None = None


class DecisionHistory(BaseModel):
    """Every assessment in the chain and every recorded event on them, oldest first."""

    application_id: int
    assessments: list[AssessmentRecord]
    events: list[DecisionEvent]
    note: str | None = Field(
        default=None,
        description="Set when part of the history predates the audit trail (release 1.10).",
    )
