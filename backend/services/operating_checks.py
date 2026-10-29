"""Use collected operating figures without fabricating learned credit effects."""
from datetime import datetime, timezone
import math
import re

from operating_schemas import OperatingFigures, OperatingMetric, OperatingReport


FIELD_USES = {
    'tenure_months': 'Principal-only monthly payment and typed cash-flow coverage',
    'existing_debt_pkr': 'Outstanding debt relative to annual typed cash flow',
    'inventory_turnover': 'Implied stock cycle in days',
    'order_consistency': 'Officer estimate compared with a statement receipts-stability proxy',
    'num_employees': 'Monthly digital receipts per person, including owners',
}


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    value = numerator / denominator
    return value if math.isfinite(value) else None


def check_operating_figures(inputs: OperatingFigures, summary: dict | None = None,
                           application_id: int | None = None) -> OperatingReport:
    principal = inputs.loan_amount_pkr / inputs.tenure_months
    cash = inputs.cash_flow_proxy
    notes = [
        'These are arithmetic and evidence checks, not a trained default model or an approval recommendation.',
        'Principal-only payment excludes interest and fees. Existing debt balances do not reveal their actual monthly instalments.',
        'Digital receipts per person are not total sales, profit, productivity or a staffing risk rating.',
    ]
    reference = None
    source_hash = None
    months = None
    if isinstance(summary, dict):
        candidate = summary.get('suggested_order_consistency')
        digest = summary.get('source_sha256')
        count = summary.get('full_months')
        if (type(candidate) in (int, float) and math.isfinite(candidate) and 0 <= candidate <= 100
                and isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest)
                and type(count) is int and count >= 3):
            reference, source_hash, months = float(candidate), digest, count
    if cash < principal:
        notes.append('Typed monthly cash flow is below the new principal-only payment; the figures need officer review.')
    if not cash:
        notes.append('Cash-flow ratios are unavailable at zero cash flow. Zero is not missing data.')
    if not inputs.inventory_turnover:
        notes.append('Stock cycle is unavailable at zero turnover; no finite holding period can be inferred.')
    if not inputs.num_employees:
        notes.append('Receipts per person are unavailable at zero headcount. Check whether owners were counted.')
    notes.append('Receipt stability measures monthly inflows, not order volumes. An order ledger is needed to verify order consistency.')
    metrics = [
        OperatingMetric(name='principal_per_month', label='New principal per month', value=principal, unit='PKR',
                        formula='loan amount / tenure months', note='Straight-line principal only; not a lender repayment quote.'),
        OperatingMetric(name='cash_after_principal', label='Typed cash flow after new principal', value=cash - principal, unit='PKR',
                        formula='monthly cash-flow proxy - new principal per month', note='An arithmetic remainder, not verified disposable cash. Existing repayments may already be in net cash flow.'),
        OperatingMetric(name='principal_cashflow_ratio', label='New principal / typed monthly cash flow', value=_ratio(principal, cash), unit='ratio',
                        formula='new principal per month / monthly cash-flow proxy', note='Does not include interest, fees or a verified existing-debt schedule; not DSCR.'),
        OperatingMetric(name='debt_annual_cashflow_ratio', label='Existing debt / annual typed cash flow', value=_ratio(inputs.existing_debt_pkr, 12 * cash), unit='ratio',
                        formula='existing debt / (12 × monthly cash-flow proxy)', note='Outstanding balance relative to a flow. This is not monthly debt service or debt-to-income.'),
        OperatingMetric(name='stock_cycle_days', label='Implied stock cycle', value=_ratio(365, inputs.inventory_turnover), unit='days',
                        formula='365 / annual inventory turnover', note='Uses the entered annual turnover convention; compare only with records using the same inventory definition.'),
        OperatingMetric(name='digital_receipts_per_person', label='Monthly digital receipts per person', value=inputs.monthly_digital_payments / inputs.num_employees if inputs.num_employees else None, unit='PKR',
                        formula='monthly digital payments / headcount including owners', note='A descriptive operating figure. No sector benchmark or credit penalty is applied.'),
        OperatingMetric(name='order_consistency_gap', label='Entered consistency minus receipts proxy', value=inputs.order_consistency - reference if reference is not None else None, unit='points',
                        formula='entered order consistency - statement receipts-stability proxy', note='Different measures can differ legitimately. A zero gap does not verify orders or income.'),
    ]
    if any(row.value is None for row in metrics[:6]) and cash and inputs.inventory_turnover and inputs.num_employees:
        notes.append('A ratio exceeds finite numeric precision and is withheld; check the source figures.')
    return OperatingReport(computed_at=datetime.now(timezone.utc), application_id=application_id,
                           inputs=inputs, metrics=metrics,
                           order_source='statement_receipts_proxy' if reference is not None else 'officer_entered',
                           receipt_consistency_reference=reference, statement_sha256=source_hash,
                           statement_full_months=months, notes=notes)
