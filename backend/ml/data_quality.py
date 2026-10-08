"""A reusable data-quality report for a training file.

Run from the ``backend`` directory (``ml.train_real_model`` also writes it)::

    python -m ml.data_quality

The report describes the raw file and what the training protocol does to it.
Every statistic here is descriptive: nothing is learned from it, so it may
look at the whole file. The learned preprocessing parameters (medians, clip
bounds) come from the training split only and are listed separately.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ml.features import ML_DIR

DATA_QUALITY_PATH = ML_DIR / "data_quality_report.json"

# Plausible ranges for the consumer file's columns. A value outside is counted,
# not removed: the training split's 1st/99th percentile clip handles it.
CREDIT_RISK_VALID_RANGES: dict[str, tuple[float | None, float | None]] = {
    "person_age": (18, 100),
    "person_income": (1, None),
    "person_emp_length": (0, 60),
    "loan_amnt": (1, None),
    "loan_int_rate": (0, 100),
    "loan_percent_income": (0, 1),
    "cb_person_cred_hist_length": (0, 80),
}


def _describe(series: pd.Series) -> dict:
    values = series.dropna()
    if pd.api.types.is_numeric_dtype(series):
        quantiles = values.quantile([0.0, 0.01, 0.25, 0.5, 0.75, 0.99, 1.0]) if len(values) else None
        return {
            "kind": "numeric",
            "mean": float(values.mean()) if len(values) else None,
            "std": float(values.std()) if len(values) > 1 else None,
            "quantiles": (
                {f"p{int(q * 100)}": float(v) for q, v in quantiles.items()} if quantiles is not None else {}
            ),
        }
    counts = values.astype(str).value_counts()
    return {
        "kind": "categorical",
        "levels": {str(level): int(count) for level, count in counts.head(25).items()},
    }


def data_quality_report(
    raw: pd.DataFrame,
    target: str,
    *,
    dataset_identifier: str,
    dataset_type_label: str,
    dataset_sha256: str | None = None,
    valid_ranges: dict[str, tuple[float | None, float | None]] | None = None,
    excluded: dict[str, int] | None = None,
    preprocessing: list[str] | None = None,
    learned_parameters: dict | None = None,
    model_features: list[str] | None = None,
    mapped: pd.DataFrame | None = None,
) -> dict:
    """Profile ``raw`` and record what training does to it."""
    rows, columns = raw.shape
    y = raw[target]
    positives = int(y.sum())
    invalid = {}
    for column, (low, high) in (valid_ranges or {}).items():
        if column not in raw:
            continue
        values = raw[column].dropna()
        mask = pd.Series(False, index=values.index)
        if low is not None:
            mask |= values < low
        if high is not None:
            mask |= values > high
        invalid[column] = {
            "rule": f"{'' if low is None else low} to {'' if high is None else high}".strip(),
            "out_of_range_rows": int(mask.sum()),
        }
    report = {
        "dataset_identifier": dataset_identifier,
        "dataset_type": dataset_type_label,
        "not_this": "Not Pakistani SME banking data. No Pakistani SME loan is in this file.",
        "dataset_sha256": dataset_sha256,
        "rows": int(rows),
        "columns": int(columns),
        "target": {
            "column": target,
            "positives": positives,
            "negatives": int(rows - positives),
            "positive_rate": float(positives / rows) if rows else None,
            "imbalance_ratio": float((rows - positives) / positives) if positives else None,
        },
        "duplicate_rows": int(raw.duplicated().sum()),
        "missing_values": {
            column: {"rows": int(count), "share": float(count / rows)}
            for column, count in raw.isna().sum().items()
            if count
        },
        "unique_values": {column: int(raw[column].nunique(dropna=True)) for column in raw.columns},
        "invalid_values": invalid,
        "distributions": {column: _describe(raw[column]) for column in raw.columns},
        "excluded_rows": excluded or {},
        "preprocessing_actions": preprocessing or [],
        "learned_parameters_from_training_split": learned_parameters or {},
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if model_features:
        report["model_features"] = model_features
        report["feature_count"] = len(model_features)
    if mapped is not None and model_features:
        report["model_feature_missing_values"] = {
            column: int(mapped[column].isna().sum()) for column in model_features
        }
        report["model_feature_distributions"] = {
            column: _describe(mapped[column]) for column in model_features
        }
    return report


def write_report(report: dict, path: Path = DATA_QUALITY_PATH) -> None:
    path.write_text(json.dumps(report, indent=2, default=_json_default), encoding="utf-8")


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    raise TypeError(f"not serialisable: {type(value)}")


def load_data_quality() -> dict | None:
    if not DATA_QUALITY_PATH.exists():
        return None
    return json.loads(DATA_QUALITY_PATH.read_text(encoding="utf-8"))


def main() -> int:
    """Profile the training file on its own (training writes the full version)."""
    from ml import pipeline

    prepared = pipeline.load_prepared()
    report = data_quality_report(
        pd.read_csv(pipeline.DATA_DIR / pipeline.DATASET_FILE),
        "loan_status",
        dataset_identifier=pipeline.DATASET_IDENTIFIER,
        dataset_type_label=pipeline.DATASET_TYPE_LABEL,
        dataset_sha256=prepared.dataset_sha256,
        valid_ranges=CREDIT_RISK_VALID_RANGES,
        excluded=prepared.excluded,
        model_features=pipeline.MODEL_FEATURES,
        mapped=prepared.frame,
    )
    write_report(report)
    print(json.dumps({k: report[k] for k in ("rows", "columns", "duplicate_rows", "target")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
