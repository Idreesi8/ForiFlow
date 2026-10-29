"""Unsaved input inspection; no credit inference, identity or database writes."""
from business_time import utc_now
from diagnostic_schemas import ModelInputReport
from ml.features import (
    FEATURE_LABELS, NO_CASH_FLOW_RATIO, apply_clips, monthly_turnover_proxy,
    snap_payment_history,
)
from services import applicability_service

SUPPORTED_FEATURES = {'loan_to_income', 'payment_history_score', 'years_in_operation'}
NOTES = [
    'Only the five submitted financial figures are checked. No applicant identity, statement or source document is verified.',
    'No credit score, recommendation, borrower, assessment or officer decision is created or updated.',
    'The credit and anomaly models use public consumer credit data and are not validated for Pakistani SME lending.',
]


def describe_inputs(scorer, raw, effective):
    """Use the same transformation descriptions for draft and saved-case checks."""
    checks = []
    for name in scorer.feature_names:
        lower, upper = scorer.feature_clips[name]
        if name == 'payment_history_score' and scorer.history_levels is not None:
            transformation = 'clean_history' if effective[name] == max(scorer.history_levels) else 'adverse_history'
            clipped = False
        else:
            clipped = raw[name] < lower or raw[name] > upper
            transformation = 'clipped_low' if raw[name] < lower else 'clipped_high' if raw[name] > upper else 'unchanged'
        checks.append({'name': name, 'label': FEATURE_LABELS.get(name, name), 'entered': raw[name],
                       'model_value': effective[name], 'training_lower': lower, 'training_upper': upper,
                       'clipped': clipped, 'transformation': transformation})
    return checks


def check_inputs(request, scorer) -> ModelInputReport:
    base = dict(computed_at=utc_now(), inputs=request, model_version=scorer.model_version, notes=NOTES)
    if scorer.engine != 'ml' or set(scorer.feature_names) != SUPPORTED_FEATURES:
        return ModelInputReport(**base, status='unavailable',
            reason='These unsaved input checks require the supported three-feature trained credit model. No result is inferred from a demo formula or a different feature contract.')
    # The five-field contract covers exactly the inputs for these three features.
    # Keep the turnover source, zero-flow rule, clipping and history encoding
    # identical to ml.features; parity with the full scoring path is tested.
    monthly = monthly_turnover_proxy(request)
    raw = {'loan_to_income': request.loan_amount_pkr / (12 * monthly) if monthly > 0 else NO_CASH_FLOW_RATIO,
           'payment_history_score': request.payment_history_score,
           'years_in_operation': request.years_in_operation}
    effective = apply_clips(raw, scorer.feature_clips)
    if scorer.history_levels is not None:
        effective['payment_history_score'] = snap_payment_history(raw['payment_history_score'], scorer.history_levels)
    applicability = applicability_service.assess(scorer, raw)
    return ModelInputReport(**base, status='ready' if applicability['status'] == 'ready' else 'partial',
        reason=None if applicability['status'] == 'ready' else 'Anomaly analysis is unavailable. Credit-input transformations are still shown.',
        credit_artifact_sha256=scorer.artifact_sha256, input_checks=describe_inputs(scorer, raw, effective),
        applicability=applicability)
