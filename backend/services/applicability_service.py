"""Load the locally trusted, fingerprint-bound input-anomaly model."""
from __future__ import annotations

import hashlib
import io
import json
import math
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path

from ml.features import ML_DIR, snap_payment_history

MODEL_PATH = ML_DIR / 'applicability_model.pkl'
MANIFEST_PATH = ML_DIR / 'applicability_model.json'


class ApplicabilityUnavailable(ValueError):
    pass


@lru_cache(maxsize=1)
def _restore_verified(model_bytes: bytes):
    import joblib
    return joblib.load(io.BytesIO(model_bytes))  # Locally built artefact, never user-uploaded data.


def load_reference(scorer):
    import sklearn
    try:
        manifest_bytes = MANIFEST_PATH.read_bytes()
        manifest = json.loads(manifest_bytes)
        model_bytes = MODEL_PATH.read_bytes()
    except (OSError, ValueError) as error:
        raise ApplicabilityUnavailable('The input-anomaly model is not available.') from error
    if not isinstance(manifest, dict):
        raise ApplicabilityUnavailable('The input-anomaly reference could not be read.')
    required = ('trained_at', 'random_seed', 'n_estimators', 'dataset_type', 'validation_rows',
                'validation_ids_sha256', 'training_flagged', 'validation_flagged', 'representation', 'interpretation')
    if any(key not in manifest for key in required):
        raise ApplicabilityUnavailable('The input-anomaly reference is incomplete.')
    if (manifest.get('schema_version') != 1 or manifest.get('algorithm') != 'IsolationForest'
            or manifest.get('purpose') != 'input_applicability_not_default_prediction'
            or manifest.get('credit_artifact_sha256') != scorer.artifact_sha256
            or manifest.get('credit_model_version') != scorer.model_version
            or manifest.get('feature_names') != scorer.feature_names
            or manifest.get('dataset_sha256') != scorer.metadata.get('dataset_sha256')
            or manifest.get('train_ids_sha256') != scorer.metadata.get('split', {}).get('id_sha256', {}).get('train')
            or manifest.get('validation_ids_sha256') != scorer.metadata.get('split', {}).get('id_sha256', {}).get('validation')
            or manifest.get('imputation_medians') != scorer.metadata.get('feature_medians')
            or manifest.get('final_test_used') is not False):
        raise ApplicabilityUnavailable('The input-anomaly reference does not match the serving credit model.')
    if manifest.get('sklearn_version') != sklearn.__version__:
        raise ApplicabilityUnavailable('The input-anomaly model needs a matching inference runtime.')
    if hashlib.sha256(model_bytes).hexdigest() != manifest.get('artifact_sha256'):
        raise ApplicabilityUnavailable('The input-anomaly artefact failed its fingerprint check.')
    scores, threshold = manifest.get('training_scores_sorted'), manifest.get('threshold')
    if (not isinstance(scores, list) or len(scores) != manifest.get('train_rows') or len(scores) < 256
            or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in scores)
            or scores != sorted(scores) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold)
            or manifest.get('flag_quantile') != 0.95 or not isinstance(manifest.get('validation_rows'), int)
            or manifest['validation_rows'] < 1
            or type(manifest.get('training_flagged')) is not int or not 0 <= manifest['training_flagged'] <= len(scores)
            or type(manifest.get('validation_flagged')) is not int or not 0 <= manifest['validation_flagged'] <= manifest['validation_rows']):
        raise ApplicabilityUnavailable('The input-anomaly reference statistics could not be verified.')
    try:
        detector = _restore_verified(model_bytes)
    except Exception as error:
        raise ApplicabilityUnavailable('The input-anomaly model could not be loaded.') from error
    if (getattr(detector, 'n_features_in_', None) != len(scorer.feature_names)
            or len(getattr(detector, 'estimators_', [])) != manifest.get('n_estimators')):
        raise ApplicabilityUnavailable('The input-anomaly feature order could not be verified.')
    manifest['reference_sha256'] = hashlib.sha256(model_bytes + manifest_bytes).hexdigest()
    return detector, manifest


def summary(scorer) -> dict:
    if scorer.engine != 'ml':
        return {'status': 'unavailable', 'reason': 'Input applicability requires the trained credit ensemble.'}
    try:
        _, manifest = load_reference(scorer)
    except ApplicabilityUnavailable as error:
        return {'status': 'unavailable', 'reason': str(error)}
    return {
        'status': 'ready', **{key: manifest[key] for key in (
            'algorithm', 'n_estimators', 'trained_at', 'random_seed', 'credit_model_version',
            'credit_artifact_sha256', 'artifact_sha256', 'reference_sha256', 'dataset_type', 'feature_names',
            'train_rows', 'validation_rows', 'train_ids_sha256', 'validation_ids_sha256',
            'flag_quantile', 'threshold', 'training_flagged', 'validation_flagged',
            'final_test_used', 'representation', 'interpretation',
        )},
    }


def assess(scorer, raw_features: dict) -> dict:
    try:
        detector, manifest = load_reference(scorer)
    except ApplicabilityUnavailable as error:
        return {'status': 'unavailable', 'reason': str(error)}
    values = dict(raw_features)
    if scorer.history_levels is not None and 'payment_history_score' in scorer.feature_names:
        values['payment_history_score'] = snap_payment_history(values['payment_history_score'], scorer.history_levels)
    vector = [[values[name] for name in scorer.feature_names]]
    if not all(math.isfinite(value) for value in vector[0]):
        raise ValueError('Non-finite model inputs.')
    score = float(-detector.score_samples(vector)[0])
    if not math.isfinite(score):
        raise ValueError('Non-finite input-applicability score.')
    percentile = 100 * bisect_right(manifest['training_scores_sorted'], score) / manifest['train_rows']
    return {
        'status': 'ready', 'atypical': score > manifest['threshold'],
        'anomaly_score': score, 'training_percentile': round(percentile, 2),
        'threshold': manifest['threshold'], 'flag_quantile': manifest['flag_quantile'],
        'artifact_sha256': manifest['artifact_sha256'], 'train_rows': manifest['train_rows'],
        'reference_sha256': manifest['reference_sha256'],
        'interpretation': manifest['interpretation'],
    }
