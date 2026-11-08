"""Contract entries and recorded allocations, not inferred or bank-verified payments."""
from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Entry(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)


class DueItem(Entry):
    due_on: date
    amount_pkr: Decimal = Field(gt=0, le=1_000_000_000, max_digits=12, decimal_places=2)


class ScheduleCreate(Entry):
    submission_key: UUID
    expected_schedule_id: int | None = Field(..., ge=1)
    disbursed_on: date
    items: list[DueItem] = Field(min_length=1, max_length=120)
    source_note: str = Field(min_length=10, max_length=500)

    @model_validator(mode='after')
    def ordered(self):
        dates = [item.due_on for item in self.items]
        if dates != sorted(set(dates)) or dates[0] < self.disbursed_on:
            raise ValueError('Due dates must be unique, increasing, and on or after disbursement.')
        return self


class Allocation(Entry):
    installment: int = Field(ge=1, le=120, strict=True)
    amount_pkr: Decimal = Field(gt=0, le=1_000_000_000, max_digits=12, decimal_places=2)


class ReceiptCreate(Entry):
    submission_key: UUID
    expected_schedule_id: int = Field(ge=1, strict=True)
    paid_on: date
    reference: str = Field(min_length=3, max_length=80)
    allocations: list[Allocation] = Field(min_length=1, max_length=120)

    @field_validator('reference')
    @classmethod
    def canonical_reference(cls, value):
        value = value.upper()
        if len(value) > 80:
            raise ValueError('The normalised payment reference must fit within 80 characters.')
        return value

    @model_validator(mode='after')
    def distinct(self):
        if len({item.installment for item in self.allocations}) != len(self.allocations):
            raise ValueError('Each instalment can appear only once per receipt.')
        return self


class ReceiptVoid(Entry):
    reason: str = Field(min_length=10, max_length=500)
