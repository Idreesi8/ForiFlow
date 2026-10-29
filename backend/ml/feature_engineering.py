"""Reproducible, train-only feature research. Never exports a serving model.

Run from backend: python -m ml.feature_engineering --output ../archive/<new-run>
The existing validation and previously evaluated final-test partitions are
excluded from all diagnostics, fitting, permutation checks and metrics.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE, SMOTENC
from imblearn.pipeline import Pipeline
from sklearn.base import BaseEstimator, TransformerMixin, clone
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from ml import pipeline as protocol
from ml.features import ML_DIR, load_feature_metadata

VERSION = 'feature-research-v1'
FEATURES = list(protocol.MODEL_FEATURES)
CANDIDATES = {
    'ensemble_smote': 'Current ensemble recipe',
    'ensemble_smotenc': 'Ensemble with categorical history sampling',
    'logistic_smotenc': 'Linear logistic reference with categorical sampling',
    'engineered_logistic_smotenc': 'Logistic with log transforms and interactions',
}
ENGINEERED_NAMES = ['log_loan_ratio', 'adverse_history', 'log_duration',
                    'log_ratio_x_adverse', 'log_ratio_over_one_plus_duration']
ARTIFACTS = ['foriflow_model.pkl', 'scaler.pkl', 'shap_explainer.pkl',
             'feature_names.json', 'applicability_model.pkl', 'applicability_model.json']


class ResearchFeatures(BaseEstimator, TransformerMixin):
    """Five fixed algebraic terms from three existing inputs; no new evidence."""

    def fit(self, X, y=None):
        self.transform(X)
        return self

    def transform(self, X):
        values = np.asarray(X, dtype=float)
        if values.ndim != 2 or values.shape[1] != 3 or not np.isfinite(values).all():
            raise ValueError('Expected three finite, preprocessed features in canonical order.')
        ratio, history, duration = values.T
        if (ratio < 0).any() or (duration < 0).any():
            raise ValueError('Ratio and duration must be nonnegative.')
        log_ratio = np.log1p(ratio)
        adverse = (history <= 52.5).astype(float)
        return np.column_stack([log_ratio, adverse, np.log1p(duration),
                                log_ratio * adverse, log_ratio / (1 + duration)])


def build_candidate(name: str):
    if name not in CANDIDATES:
        raise ValueError('Unknown predeclared candidate.')
    categorical = name != 'ensemble_smote'
    sampler = SMOTENC(categorical_features=[1], random_state=protocol.SEED, k_neighbors=5) if categorical else SMOTE(random_state=protocol.SEED, k_neighbors=5)
    steps = [('preprocess', protocol.TrainOnlyPreprocessor())]
    # The categorical index refers to canonical history, before any expansion.
    # Scale continuous distances on fit rows; the two scaled categories remain
    # distinct, and are inverse-transformed before fixed feature engineering.
    steps += [('sampling_scale', StandardScaler()), ('sample', sampler)]
    if name.startswith('ensemble'):
        model = protocol.build_estimator('ensemble', FEATURES)
        for _, member in model.estimators:
            member.set_params(n_jobs=1)
    else:
        # ResearchFeatures expects original units. A second scaler below keeps
        # regularisation comparable. InverseSamplingScale is bound at fit time
        # by run_fold, after fitting the sampling scaler on these same fit rows.
        if name.startswith('engineered'):
            steps += [('unscale', InverseSamplingScale()), ('engineer', ResearchFeatures()),
                      ('model_scale', StandardScaler())]
        model = LogisticRegression(max_iter=2000, random_state=protocol.SEED)
    steps.append(('model', model))
    return Pipeline(steps)


class InverseSamplingScale(BaseEstimator, TransformerMixin):
    """Reconstruct canonical units without learning from generated observations."""

    def __init__(self, mean=None, scale=None):
        self.mean = mean
        self.scale = scale

    def fit(self, X, y=None):
        if self.mean is None or self.scale is None:
            raise ValueError('Original fit-only scaling parameters are required.')
        return self

    def transform(self, X):
        # Round-off near zero can make log1p inputs very slightly negative.
        result = np.asarray(X) * np.asarray(self.scale) + np.asarray(self.mean)
        result[:, [0, 2]] = np.maximum(result[:, [0, 2]], 0)
        return result


def fit_candidate(name, X, y):
    learner = build_candidate(name)
    if 'unscale' in learner.named_steps:
        # Fit only on this fold's original fit rows, exactly as the pipeline
        # will do. No validation values or SMOTE-generated values are involved.
        clean = protocol.TrainOnlyPreprocessor().fit_transform(X)
        scaler = StandardScaler().fit(clean)
        learner.set_params(unscale__mean=scaler.mean_, unscale__scale=scaler.scale_)
    learner.fit(X, y)
    return learner


def artefact_hashes():
    return {name: protocol.file_sha256(ML_DIR / name) for name in ARTIFACTS}


def check_reference(prepared, split, metadata):
    """Refuse a different data file, feature contract or original partition."""
    if prepared.dataset_sha256 != metadata.get('dataset_sha256'):
        raise ValueError('Dataset SHA-256 differs from the served training reference.')
    if metadata.get('feature_names') != FEATURES:
        raise ValueError('Serving feature contract differs from this study.')
    expected = metadata.get('split', {}).get('id_sha256', {})
    for name, ids in [('train', split.train), ('validation', split.validation), ('final_test', split.test)]:
        if protocol.ids_sha256(ids) != expected.get(name):
            raise ValueError(f'Original {name} membership does not match the serving reference.')


def training_diagnostics(X, y, raw):
    clean = protocol.TrainOnlyPreprocessor().fit(X)
    processed = pd.DataFrame(clean.transform(X), columns=FEATURES, index=X.index)
    features = []
    for name in FEATURES:
        lower, upper = clean.clips_[name]
        features.append({'name': name, 'missing_rows': int(X[name].isna().sum()),
                         'clipped_low_rows': int((X[name] < lower).sum()),
                         'clipped_high_rows': int((X[name] > upper).sum()),
                         'lower': lower, 'upper': upper, 'median': clean.medians_[name]})
    vectors = processed.assign(target=y.to_numpy()).groupby(FEATURES, dropna=False)['target'].agg(['size', 'nunique'])
    contradictory = vectors[vectors['nunique'] > 1]
    return {'rows': len(X), 'features': features,
            'unique_model_vectors': len(vectors),
            'rows_in_repeated_vectors': int(vectors.loc[vectors['size'] > 1, 'size'].sum()),
            'rows_in_conflicting_vectors': int(contradictory['size'].sum()),
            'conflicting_vectors': len(contradictory),
            'unknown_prior_default_rows': int((~raw['cb_person_default_on_file'].isin(['Y', 'N'])).sum()),
            'note': 'Identical effective inputs can have different outcomes. This is an information limit, not proof of incorrectly labelled records.'}


def sampling_diagnostics(learner, X, y):
    clean = learner.named_steps['preprocess'].transform(X)
    scaler = learner.named_steps['sampling_scale']
    before = scaler.transform(clean)
    after, _ = clone(learner.named_steps['sample']).fit_resample(before, y)
    generated = scaler.inverse_transform(np.asarray(after)[len(X):])
    fraction = np.minimum(abs(generated[:, 1] - 25), abs(generated[:, 1] - 80)) > 1e-7
    return {'synthetic_rows': len(generated), 'non_category_history_rows': int(fraction.sum())}


def run_cv(X, y, *, candidates=None, folds=5, on_progress=print):
    """Caller supplies ONLY verified training rows. Shared fit/score folds."""
    names = list(candidates or CANDIDATES)
    if len(X) != len(y) or not X.index.equals(y.index) or X.columns.tolist() != FEATURES:
        raise ValueError('Training frame and labels must have identical indices and canonical columns.')
    predictions = {name: np.full(len(X), np.nan) for name in names}
    results = {name: [] for name in names}
    permutation = {feature: [] for feature in FEATURES}
    fold_records = []
    with threadpool_limits(limits=1):
        for number, (fit, score) in enumerate(StratifiedKFold(n_splits=folds, shuffle=True, random_state=42).split(X, y), 1):
            Xfit, yfit, Xscore, yscore = X.iloc[fit], y.iloc[fit], X.iloc[score], y.iloc[score]
            fold_records.append({'fold': number, 'fit_rows': len(fit), 'score_rows': len(score),
                                 'fit_ids_sha256': protocol.ids_sha256(Xfit.index),
                                 'score_ids_sha256': protocol.ids_sha256(Xscore.index)})
            for name in names:
                started = time.monotonic()
                learner = fit_candidate(name, Xfit, yfit)
                p = learner.predict_proba(Xscore)[:, 1]
                predictions[name][score] = p
                metrics = protocol.classification_metrics(yscore.to_numpy(), p)
                metrics['seconds'] = time.monotonic() - started
                if name.startswith('ensemble'):
                    metrics['sampling'] = sampling_diagnostics(learner, Xfit, yfit)
                results[name].append(metrics)
                if name == 'ensemble_smote':
                    # Permute original raw inputs, then use the already fitted
                    # fold pipeline. No fitting or tuning on the score rows.
                    for column in FEATURES:
                        changes = []
                        for repeat in range(3):
                            shuffled = Xscore.copy()
                            rng = np.random.default_rng(1000 * number + repeat)
                            shuffled[column] = rng.permutation(shuffled[column].to_numpy())
                            changes.append(metrics['auc_roc'] - roc_auc_score(yscore, learner.predict_proba(shuffled)[:, 1]))
                        permutation[column].append(float(np.mean(changes)))
                on_progress(f'Fold {number}/{folds}: {name}: ROC-AUC={metrics["auc_roc"]:.5f}', flush=True)
    summary = []
    for name in names:
        if not np.isfinite(predictions[name]).all():
            raise ValueError('Incomplete out-of-fold predictions.')
        row = {'id': name, 'label': CANDIDATES[name], 'per_fold': results[name],
               'oof': protocol.classification_metrics(y.to_numpy(), predictions[name])}
        for metric in ['auc_roc', 'pr_auc', 'brier']:
            values = [fold[metric] for fold in results[name]]
            row[metric + '_mean'] = float(np.mean(values))
            row[metric + '_std'] = float(np.std(values))
        if 'ensemble_smote' in results:
            row['paired_auc_deltas_vs_current'] = [fold['auc_roc'] - ref['auc_roc'] for fold, ref in zip(results[name], results['ensemble_smote'])]
        summary.append(row)
    return {'candidates': summary, 'folds': fold_records,
            'permutation': [{'name': column, 'per_fold_auc_drop': values,
                             'mean_auc_drop': float(np.mean(values))} for column, values in permutation.items() if values]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='A new research directory; never the serving artefact folder.')
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination == ML_DIR.resolve() or ML_DIR.resolve() in destination.parents:
        raise ValueError('Research output must be outside the serving artefact directory.')
    destination.mkdir(parents=True, exist_ok=False)
    prepared = protocol.load_prepared()
    split = protocol.split_rows(prepared.frame)
    metadata = load_feature_metadata()
    check_reference(prepared, split, metadata)
    X = prepared.frame.loc[split.train, FEATURES].copy()
    y = prepared.frame.loc[split.train, protocol.TARGET].copy()
    raw = prepared.raw.loc[split.train]
    before = artefact_hashes()
    manifest = {'version': VERSION, 'started_at': datetime.now(timezone.utc).isoformat(),
                'dataset_sha256': prepared.dataset_sha256, 'training_rows': len(X),
                'training_ids_sha256': protocol.ids_sha256(X.index),
                'excluded_partitions': {'validation': len(split.validation), 'previously_evaluated_final_test': len(split.test)},
                'candidate_ids': list(CANDIDATES), 'features': FEATURES, 'engineered_features': ENGINEERED_NAMES,
                'folds': 5, 'seed': 42, 'permutation_repeats': 3,
                'primary_metric': 'Mean fold ROC-AUC; paired differences are descriptive, not independent hypothesis tests.',
                'sampling': 'SMOTE or SMOTENC on fit-only standardised inputs, before feature expansion.',
                'code_sha256': {str(path.relative_to(ML_DIR)): protocol.file_sha256(path) for path in [Path(__file__), ML_DIR / 'pipeline.py', ML_DIR / 'train_real_model.py']},
                'software': {package: importlib.metadata.version(package) for package in ['numpy', 'pandas', 'scikit-learn', 'imbalanced-learn', 'xgboost']},
                'python': platform.python_version(), 'serving_artifacts': before,
                'promotion': 'Research only. No model export, tuning on validation/final test, or automatic promotion.'}
    manifest_bytes = (json.dumps(manifest, indent=2, allow_nan=False) + '\n').encode()
    (destination / 'protocol.json').write_bytes(manifest_bytes)
    diagnostics = training_diagnostics(X, y, raw)
    # Discard excluded rows before any fitting or exploration starts.
    del prepared, split, raw
    results = run_cv(X, y)
    after = artefact_hashes()
    if before != after:
        raise RuntimeError('Serving artefacts changed while the research was running.')
    report = {'version': VERSION, 'completed_at': datetime.now(timezone.utc).isoformat(),
              'protocol_sha256': hashlib.sha256(manifest_bytes).hexdigest(), 'protocol': manifest,
              'training_diagnostics': diagnostics, **results,
              'serving_artifacts_unchanged': True, 'promoted': False,
              'limitations': [
                  'Exploratory comparisons on the existing training split; these are not fresh final-test estimates or live portfolio results.',
                  'All candidates use the same three source inputs. Algebraic expansion adds no new observed evidence.',
                  'The engineered logistic candidate has no guaranteed monotonicity; serving approval-path guarantees do not apply.',
                  'Source employment length and personal income remain imperfect analogues for SME business age and turnover.',
                  'SMOTE-balanced probabilities are uncalibrated. Brier scores here are research diagnostics, not lending risk estimates.',
                  'Permutation drops describe model dependence, not causal effects or an action a borrower should take.',
                  'Paired folds share training observations. Multiple candidate comparisons are exploratory; no significance or superiority claim is made.',
                  'New SME fields still need matching measurements and prospectively timed outcome labels before credit-model training.'
              ]}
    (destination / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(f'Research complete: {destination / "report.json"}. No serving model was exported.')


if __name__ == '__main__':
    main()
