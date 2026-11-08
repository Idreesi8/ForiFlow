"""Evidence metadata, not a signature, legal opinion or data-access grant."""
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FinancialField = Literal['loan_amount_pkr', 'tenure_months', 'monthly_digital_payments', 'payment_history_score',
    'inventory_turnover', 'order_consistency', 'existing_debt_pkr', 'cash_flow_proxy', 'years_in_operation', 'num_employees']
Purpose = Literal['credit_assessment', 'loan_monitoring', 'model_research']
SourceKind = Literal['bank_statement', 'wallet_statement', 'pos', 'accounting', 'bureau_extract', 'applicant_declaration', 'other']
FIELD_LABELS = {'loan_amount_pkr': 'Requested facility (PKR)', 'tenure_months': 'Tenure (months)',
    'monthly_digital_payments': 'Monthly digital receipts (PKR)', 'payment_history_score': 'Repayment history score',
    'inventory_turnover': 'Inventory turnover', 'order_consistency': 'Order consistency', 'existing_debt_pkr': 'Existing debt (PKR)',
    'cash_flow_proxy': 'Monthly cash-flow proxy (PKR)', 'years_in_operation': 'Years in operation', 'num_employees': 'Employees'}


class RecordCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    submission_key: UUID
    source_kind: SourceKind
    source_reference: str = Field(min_length=3, max_length=160)
    captured_on: date
    period_from: date | None = None
    period_to: date | None = None
    input_fields: list[FinancialField] = Field(min_length=1, max_length=10)
    permission_basis: Literal['not_recorded', 'consent_record', 'lender_authority_record']
    permission_reference: str | None = Field(default=None, min_length=3, max_length=160)
    permission_on: date | None = None
    permission_expires_on: date | None = None
    purposes: list[Purpose] = Field(min_length=1, max_length=3)
    note: str = Field(min_length=10, max_length=500)

    @field_validator('input_fields', 'purposes')
    @classmethod
    def unique_sorted(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('Duplicate fields or purposes are not accepted.')
        return sorted(value)

    @model_validator(mode='after')
    def coherent(self):
        if (self.period_from is None) != (self.period_to is None):
            raise ValueError('Provide both source-period dates or neither.')
        if self.period_from and not self.period_from <= self.period_to <= self.captured_on:
            raise ValueError('Source period must be ordered and end no later than capture.')
        if self.permission_basis == 'not_recorded':
            if any(value is not None for value in (self.permission_reference, self.permission_on, self.permission_expires_on)):
                raise ValueError('Unrecorded permission cannot carry documentary permission details.')
        elif not self.permission_reference or self.permission_on is None:
            raise ValueError('Documented permission needs a reference and evidence date.')
        if self.permission_expires_on and self.permission_expires_on < self.permission_on:
            raise ValueError('Permission expiry cannot predate its evidence date.')
        return self


class WithdrawRecord(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    submission_key: UUID
    reason: str = Field(min_length=10, max_length=500)
