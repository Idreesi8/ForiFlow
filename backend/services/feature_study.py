"""Publish and serve measured feature research, tied to its credit artefacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ml.features import ML_DIR
from services.scoring_service import artifact_fingerprint

REPORT_PATH = ML_DIR / 'feature_engineering_report.json'
CREDIT_FILES = ('foriflow_model.pkl', 'scaler.pkl', 'shap_explainer.pkl', 'feature_names.json')
NAMES = ('ensemble_smote', 'ensemble_smotenc', 'logistic_smotenc', 'engineered_logistic_smotenc')
FEATURES = ('loan_to_income', 'payment_history_score', 'years_in_operation')


class Record(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')


class Candidate(Record):
    id: str
    label: str
    auc_roc_mean: float = Field(ge=0, le=1)
    auc_roc_std: float = Field(ge=0, le=1)
    pr_auc_mean: float = Field(ge=0, le=1)
    brier_mean: float = Field(ge=0, le=1)
    paired_auc_delta: float = Field(ge=-1, le=1)


class Contribution(Record):
    name: str
    mean_auc_drop: float = Field(ge=-1, le=1)


class Sampling(Record):
    id: str
    synthetic_rows: int = Field(ge=0)
    non_category_history_rows: int = Field(ge=0)


class StudySummary(Record):
    version: str
    completed_at: datetime
    status: str = 'research_only'
    credit_artifact_sha256: str
    protocol_sha256: str
    training_rows: int = Field(gt=0)
    folds: int = Field(ge=2)
    excluded_validation_rows: int = Field(ge=0)
    excluded_final_test_rows: int = Field(ge=0)
    candidates: list[Candidate]
    permutation: list[Contribution]
    sampling: list[Sampling]
    engineered_features: list[str]
    rows_in_conflicting_vectors: int = Field(ge=0)
    unique_model_vectors: int = Field(gt=0)
    limitations: list[str]


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite report value.')))


def summarise(report) -> StudySummary:
    """Validate the fixed experiment's shape; derive table values from folds."""
    protocol = report['protocol']
    encoded = (json.dumps(protocol, indent=2, allow_nan=False) + '\n').encode()
    if hashlib.sha256(encoded).hexdigest() != report['protocol_sha256']:
        raise ValueError('Research protocol fingerprint does not match.')
    if (report['version'] != 'feature-research-v1' or report['promoted'] is not False
            or report['serving_artifacts_unchanged'] is not True
            or protocol['candidate_ids'] != list(NAMES) or protocol['features'] != list(FEATURES)
            or protocol['folds'] != 5 or [row['id'] for row in report['candidates']] != list(NAMES)
            or [row['name'] for row in report['permutation']] != list(FEATURES)):
        raise ValueError('Unsupported or incomplete feature experiment.')
    if len(report['folds']) != 5 or sum(fold['score_rows'] for fold in report['folds']) != protocol['training_rows']:
        raise ValueError('Incomplete cross-validation coverage.')
    candidates, sampling = [], []
    baseline = report['candidates'][0]['per_fold']
    for row in report['candidates']:
        folds = row['per_fold']
        if len(folds) != 5 or any(fold['rows'] != record['score_rows'] for fold, record in zip(folds, report['folds'])):
            raise ValueError('Inconsistent fold metrics.')
        values = {}
        for metric in ('auc_roc', 'pr_auc', 'brier'):
            numbers = [fold[metric] for fold in folds]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in numbers):
                raise ValueError('Invalid metric.')
            values[metric + '_mean'] = float(np.mean(numbers))
        candidates.append(Candidate(id=row['id'], label=row['label'], **values,
            auc_roc_std=float(np.std([fold['auc_roc'] for fold in folds])),
            paired_auc_delta=float(np.mean([fold['auc_roc'] - ref['auc_roc'] for fold, ref in zip(folds, baseline)]))))
        if row['id'].startswith('ensemble'):
            synthetic = sum(fold['sampling']['synthetic_rows'] for fold in folds)
            fractional = sum(fold['sampling']['non_category_history_rows'] for fold in folds)
            if not 0 <= fractional <= synthetic:
                raise ValueError('Invalid categorical sampling counts.')
            sampling.append(Sampling(id=row['id'], synthetic_rows=synthetic, non_category_history_rows=fractional))
    permutation = []
    for row in report['permutation']:
        values = row['per_fold_auc_drop']
        if len(values) != 5 or not all(isinstance(v, (int, float)) and math.isfinite(v) and -1 <= v <= 1 for v in values):
            raise ValueError('Invalid permutation measurement.')
        permutation.append(Contribution(name=row['name'], mean_auc_drop=float(np.mean(values))))
    excluded = protocol['excluded_partitions']
    diagnostics = report['training_diagnostics']
    if diagnostics['rows'] != protocol['training_rows'] or not 0 <= diagnostics['rows_in_conflicting_vectors'] <= diagnostics['rows'] or not 0 < diagnostics['unique_model_vectors'] <= diagnostics['rows']:
        raise ValueError('Invalid training information counts.')
    return StudySummary(version=report['version'], completed_at=report['completed_at'],
        credit_artifact_sha256=report['published_reference']['credit_artifact_sha256'], protocol_sha256=report['protocol_sha256'],
        training_rows=protocol['training_rows'], folds=5,
        excluded_validation_rows=excluded['validation'], excluded_final_test_rows=excluded['previously_evaluated_final_test'],
        candidates=candidates, permutation=permutation, sampling=sampling,
        engineered_features=protocol['engineered_features'],
        rows_in_conflicting_vectors=diagnostics['rows_in_conflicting_vectors'], unique_model_vectors=diagnostics['unique_model_vectors'],
        limitations=report['limitations'])


def load_study(scorer) -> StudySummary:
    report = _read(REPORT_PATH)
    if scorer.engine != 'ml' or report['published_reference']['credit_artifact_sha256'] != scorer.artifact_sha256:
        raise ValueError('This feature study does not match the active credit artefacts.')
    return summarise(report)


def publish(source: Path):
    """Explicit offline publishing step; never trains or exports an estimator."""
    report = _read(source)
    for name, expected in report['protocol']['serving_artifacts'].items():
        if hashlib.sha256((ML_DIR / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Serving artefacts changed since this experiment; publication refused.')
    report['published_reference'] = {'credit_artifact_sha256': artifact_fingerprint(ML_DIR / name for name in CREDIT_FILES)}
    summarise(report)
    # An existing research record is retained until deliberately archived.
    with REPORT_PATH.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(report, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Publish completed, validated research for the Model page.')
    parser.add_argument('source', type=Path)
    publish(parser.parse_args().source)
