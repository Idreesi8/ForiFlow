"""Case-bound ensemble behaviour and hypothetical sensitivity, with no writes."""
from __future__ import annotations

import math
from types import SimpleNamespace

from business_time import utc_now
from diagnostic_schemas import CaseDiagnostics
from ml.features import build_raw_features
from models.database import ModelVersion
from schemas import RECOMMENDATION_OF
from services import applicability_service, policy_rules
from services.feature_contract import SCORING_INTAKE_FIELDS, MODEL_FEATURE_SOURCES
from services.input_checks import describe_inputs

FACTORS = (0.8, 0.9, 1.0, 1.1, 1.2)
LIMITATIONS = [
    'The credit and input-anomaly models use public consumer credit data, not validated Pakistani SME outcomes.',
    'Input atypicality is not a default probability, fraud finding or proof of a data error. In-range inputs do not establish suitability for SME lending.',
    'Member spread is disagreement between learners trained on the same data, not a calibrated confidence interval or an accuracy guarantee.',
    'Scenarios are hypothetical model responses, not causal forecasts, approved facilities or agreed payment schedules. No saved fact or decision is changed.',
]


def _recorded_bands(application):
    stored = (application.policy_evaluation or {}).get('bands')
    if not isinstance(stored, dict):
        return None
    try:
        return policy_rules.ScoreBands(float(stored['decline_max_score']), float(stored['manual_review_max_score']))
    except (KeyError, TypeError, ValueError):
        return None


def build_diagnostics(db, application, scorer) -> CaseDiagnostics:
    base = {
        'application_id': application.id, 'computed_at': utc_now(),
        'recorded_model_version': application.model_version, 'serving_model_version': scorer.model_version,
        'stored_score': application.risk_score, 'limitations': LIMITATIONS,
    }
    def unavailable(reason):
        return CaseDiagnostics(**base, status='unavailable', reason=reason)
    if scorer.engine != 'ml' or application.scoring_engine != 'ml':
        return unavailable('These checks require a case assessed by the trained credit ensemble, while that ensemble is serving.')
    source = db.get(ModelVersion, application.model_version_id) if application.model_version_id else None
    if (source is None or source.engine != 'ml' or source.version != application.model_version
            or application.model_version != scorer.model_version or source.artifact_sha256 != scorer.artifact_sha256):
        return unavailable('The exact model artefacts behind this saved case could not be matched. Its recorded score is retained; current-model diagnostics are withheld.')

    try:
        required_fields = {'loan_amount_pkr', 'monthly_digital_payments', 'cash_flow_proxy'}
        for name in scorer.feature_names:
            required_fields.update(MODEL_FEATURE_SOURCES.get(name, {}).get('intake_fields', []))
        if not all(math.isfinite(float(getattr(application, name))) for name in required_fields):
            return unavailable('The saved case contains model inputs that cannot be analysed as finite numbers.')
        raw = build_raw_features(application)
        if not all(math.isfinite(raw[name]) for name in scorer.feature_names):
            return unavailable('The saved case contains model inputs that cannot be analysed as finite numbers.')
        scaled, effective, raw = scorer._feature_frame(application)
    except (TypeError, ValueError, OverflowError):
        return unavailable('The saved case contains model inputs that cannot be analysed as finite numbers.')
    if not all(math.isfinite(raw[name]) and math.isfinite(effective[name]) for name in scorer.feature_names):
        return unavailable('The saved case contains model inputs that cannot be analysed as finite numbers.')
    member_pds = scorer._member_probabilities(scaled)
    if not member_pds or not all(math.isfinite(value) and 0 <= value <= 1 for value in member_pds.values()):
        return unavailable('The ensemble did not return valid member predictions.')
    raw_pd = scorer._ensemble_probability(member_pds)
    score = round(100 * (1 - raw_pd), 2)
    if not math.isfinite(score) or abs(score - application.risk_score) > 0.011:
        return unavailable('The current inference path does not reproduce this saved score. Diagnostics are withheld so the recorded assessment is not silently replaced.')
    checks = describe_inputs(scorer, raw, effective)
    total_weight = sum(scorer.shap_weights[name] for name in member_pds)
    members = [{'name': name, 'label': {'xgb': 'XGBoost', 'rf': 'Random forest'}.get(name, name),
                'weight': scorer.shap_weights[name] / total_weight, 'raw_default_probability': value,
                'score': round(100 * (1 - value), 2)} for name, value in member_pds.items()]
    applicability = applicability_service.assess(scorer, raw)
    bands = _recorded_bands(application)
    if bands is not None and policy_rules.recommendation_for(score, bands).value != application.decision:
        bands = None
    recommendation = RECOMMENDATION_OF[policy_rules.recommendation_for(score, bands)].value if bands else None
    policy_note = ('Recommendations use only the score cut-offs retained with this assessment; approval authority still needs officer review.' if bands else
                   'The recorded policy cut-offs could not be reproduced. Scenario scores are shown without policy recommendations; today’s policy is not substituted.')
    inputs = {name: getattr(application, name) for name in SCORING_INTAKE_FIELDS}
    scenarios, applicants = [], []
    for loan_factor in FACTORS:
        for receipts_factor in FACTORS:
            values = {**inputs, 'loan_amount_pkr': inputs['loan_amount_pkr'] * loan_factor,
                      'monthly_digital_payments': inputs['monthly_digital_payments'] * receipts_factor,
                      'cash_flow_proxy': inputs['cash_flow_proxy'] * receipts_factor}
            applicants.append(SimpleNamespace(**values))
            scenarios.append({key: values[key] for key in ('loan_amount_pkr', 'monthly_digital_payments', 'cash_flow_proxy')} |
                             {'loan_factor': loan_factor, 'receipts_factor': receipts_factor})
    scores = scorer._scores_for(applicants)
    for row, scenario_score in zip(scenarios, scores, strict=True):
        label = RECOMMENDATION_OF[policy_rules.recommendation_for(scenario_score, bands)].value if bands else None
        row.update(score=scenario_score, score_change=round(scenario_score - score, 2), recommendation=label,
                   recommendation_changed=(label != recommendation) if label else None)
    return CaseDiagnostics(**base, status='ready' if applicability['status'] == 'ready' else 'partial',
        reason=None if applicability['status'] == 'ready' else 'Input-anomaly analysis is unavailable; verified ensemble and scenario checks are still shown.',
        credit_artifact_sha256=scorer.artifact_sha256, source_verified=True, recomputed_score=score,
        input_checks=checks, members=members, member_spread_pp=round(100 * (max(member_pds.values()) - min(member_pds.values())), 4),
        ensemble_raw_default_probability=raw_pd, applicability=applicability, policy_note=policy_note,
        baseline_recommendation=recommendation,
        nearest_policy_boundary_distance=round(min(abs(score - bands.decline_max_score), abs(score - bands.manual_review_max_score)), 2) if bands else None,
        scenarios=scenarios,
        scenario_note='Each scenario scales the requested loan and scales BOTH monthly digital receipts and the cash-flow proxy by the displayed factors. All other recorded inputs stay fixed. The model still uses max(receipts, cash flow) as its turnover proxy. Zero recorded receipts remain zero. Scores use the same clipping, repayment-history encoding and trained ensemble as the saved assessment.')
