"""Fit an input-anomaly sidecar on the credit model's original TRAIN rows only.

This is not a default-risk classifier. No credit artefact or final-test result
is replaced. The validation set is a descriptive check, never used to tune it.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest

from ml import pipeline
from ml.features import ML_DIR
from services.scoring_service import MLScoringService

TREES = 128
FLAG_QUANTILE = 0.95
MODEL_FILE = 'applicability_model.pkl'
MANIFEST_FILE = 'applicability_model.json'


def fit_reference(train, validation, features: list[str], medians: dict, *, seed: int = 42):
    """Learn structure and threshold from train only; no outcomes are read."""
    train_values = train[features].fillna(medians).to_numpy(dtype=float)
    validation_values = validation[features].fillna(medians).to_numpy(dtype=float)
    if len(train_values) < 256 or not np.isfinite(train_values).all() or not np.isfinite(validation_values).all():
        raise ValueError('Expected at least 256 finite training rows and finite validation values.')
    detector = IsolationForest(n_estimators=TREES, max_samples=256, contamination='auto', random_state=seed, n_jobs=1)
    detector.fit(train_values)
    # Higher means more unusual; use this explicitly rather than predict(),
    # whose default offset is not the chosen training-quantile threshold.
    training_scores = -detector.score_samples(train_values)
    threshold = float(np.quantile(training_scores, FLAG_QUANTILE))
    validation_scores = -detector.score_samples(validation_values)
    return detector, {
        'threshold': threshold,
        'flag_quantile': FLAG_QUANTILE,
        'training_scores_sorted': sorted(float(value) for value in training_scores),
        'training_flagged': int((training_scores > threshold).sum()),
        'validation_flagged': int((validation_scores > threshold).sum()),
    }


def build(output: Path, *, dataset: Path | None = None) -> dict:
    output = output.resolve()
    model_path, manifest_path = output / MODEL_FILE, output / MANIFEST_FILE
    if model_path.exists() or manifest_path.exists():
        raise FileExistsError('Use a new output directory; an existing sidecar is not overwritten.')
    scorer = MLScoringService.from_artifacts()
    metadata = scorer.metadata
    prepared = pipeline.load_prepared(dataset)
    if prepared.dataset_sha256 != metadata.get('dataset_sha256'):
        raise ValueError('Dataset fingerprint does not match the credit training run.')
    if list(scorer.feature_names) != list(pipeline.MODEL_FEATURES):
        raise ValueError('The current training mapping does not match the served feature order.')
    split = pipeline.split_rows(prepared.frame, seed=metadata['random_seed'])
    recorded = metadata.get('split', {}).get('id_sha256', {})
    for name, index in [('train', split.train), ('validation', split.validation), ('final_test', split.test)]:
        if pipeline.ids_sha256(index) != recorded.get(name):
            raise ValueError(f'{name} row identities do not match the original training protocol.')
    features = scorer.feature_names
    train = prepared.frame.loc[split.train, features]
    validation = prepared.frame.loc[split.validation, features]
    medians = {name: float(train[name].median()) for name in features}
    if any(not np.isclose(medians[name], metadata['feature_medians'][name], atol=1e-12) for name in features):
        raise ValueError('Training imputation does not reproduce the recorded model medians.')
    detector, results = fit_reference(train, validation, features, medians, seed=metadata['random_seed'])
    stream = io.BytesIO()
    joblib.dump(detector, stream, compress=3)
    model_bytes = stream.getvalue()
    manifest = {
        'schema_version': 1, 'purpose': 'input_applicability_not_default_prediction',
        'algorithm': 'IsolationForest', 'n_estimators': TREES, 'max_samples': 256,
        'trained_at': datetime.now(timezone.utc).isoformat(), 'random_seed': metadata['random_seed'],
        'sklearn_version': sklearn.__version__,
        'credit_model_version': scorer.model_version, 'credit_artifact_sha256': scorer.artifact_sha256,
        'artifact_sha256': hashlib.sha256(model_bytes).hexdigest(),
        'dataset_sha256': prepared.dataset_sha256, 'dataset_type': metadata['dataset_type_label'],
        'feature_names': features, 'imputation_medians': medians,
        'train_rows': len(train), 'validation_rows': len(validation),
        'train_ids_sha256': recorded['train'], 'validation_ids_sha256': recorded['validation'],
        'final_test_ids_sha256': recorded['final_test'], 'final_test_used': False,
        'representation': 'Original non-SMOTE training rows, median-imputed, without credit-score clipping; repayment history uses the original two encoded levels.',
        'interpretation': 'Atypical relative to the public consumer training reference. Not a default probability, fraud finding, data-error finding, or validation for Pakistani SMEs.',
        **results,
    }
    output.mkdir(parents=True, exist_ok=True)
    # A mismatched pair is rejected by the loader. No existing files are replaced.
    with model_path.open('xb') as handle:
        handle.write(model_bytes)
    with manifest_path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(manifest, handle, indent=2, allow_nan=False)
        handle.write('\n')
    return {key: value for key, value in manifest.items() if key != 'training_scores_sorted'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ML_DIR)
    parser.add_argument('--dataset', type=Path)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.output_dir, dataset=arguments.dataset), indent=2, allow_nan=False))
