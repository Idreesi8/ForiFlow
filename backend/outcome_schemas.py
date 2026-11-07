"""Coverage evidence for future validation, never an inferred default label."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EvidenceStatus = Literal['needs_approval_record', 'shorter_term', 'collecting', 'needs_evidence', 'covered']


class OutcomeCase(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    application_id: int
    business_name: str
    borrower_public_id: str | None
    model_version: str | None
    scoring_engine: str | None
    status: EvidenceStatus
    window_end: date | None
    recorded_months: int = Field(ge=0)
    usable_months: int = Field(ge=0)
    missing_months: list[int]
    incomplete_months: list[int]
    reasons: list[str]
    recorded_30_plus: bool


class OutcomeCounts(BaseModel):
    approved_facilities: int = Field(ge=0)
    needs_approval_record: int = Field(ge=0)
    shorter_term: int = Field(ge=0)
    collecting: int = Field(ge=0)
    needs_evidence: int = Field(ge=0)
    covered: int = Field(ge=0)
    covered_with_30_plus: int = Field(ge=0)
    distinct_linked_borrowers: int = Field(ge=0)
    additional_repeat_facilities: int = Field(ge=0)
    unlinked_facilities: int = Field(ge=0)


class OutcomeEvidence(BaseModel):
    captured_at: datetime
    as_of_date: date
    horizon_months: Literal[3, 6, 12]
    training_ready: Literal[False] = False
    basis: str
    limits: list[str]
    counts: OutcomeCounts
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    status_filter: EvidenceStatus | None
    rows: list[OutcomeCase]
