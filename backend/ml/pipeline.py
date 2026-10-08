"""The leakage-free training protocol (2.2): split first, then learn anything.

Order, enforced by the code below and by ``tests/test_ml_protocol.py``::

    raw file -> drop exact duplicate rows -> map onto ForiFlow features
             -> stratified split (train 60% / validation 20% / final test 20%)
             -> fit imputation medians, clip bounds and the scaler on TRAIN only
             -> SMOTE on the scaled TRAIN rows only (inside each CV fold too)
             -> fit the models on TRAIN
             -> choose and fit the probability calibrator on VALIDATION
             -> evaluate once on the FINAL TEST set (``ml.evaluate_model``)

Before 2.2 the medians and the 1st/99th percentile clip bounds were computed on
the whole file before the 80/20 split, and the same 20% hold-out was reused for
the evaluation, the fairness audit and the band report. Both are fixed here.

What the data is: ``credit_risk_dataset.csv``, a public file of consumer loans.
It is not Pakistani SME lending data, and nothing in this module makes it so.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import StandardScaler

from ml.features import DATA_DIR

SEED: int = 42
FINAL_TEST_FRACTION: float = 0.20
# Of the whole file; the validation set is carved out of the non-test rows.
VALIDATION_FRACTION: float = 0.20
CV_FOLDS: int = 5
CLIP_QUANTILES: tuple[float, float] = (0.01, 0.99)
PREPROCESSING_VERSION: str = "2.2.0"
TRAINING_PROTOCOL_VERSION: str = "2.2.0"

# Model evaluation threshold on the raw ensemble probability. Fixed before any
# result was seen (the conventional 0.5 for a model trained on 50/50 SMOTE
# data) and never tuned. It is not a credit policy threshold.
EVALUATION_THRESHOLD: float = 0.5

TARGET = "target"
DATASET_FILE = "credit_risk_dataset.csv"
DATASET_NAME = "credit_risk_shared"
DATASET_IDENTIFIER = "credit_risk_dataset.csv (public 'Credit Risk Dataset', consumer loans)"
DATASET_TYPE = "public_consumer_credit"
DATASET_TYPE_LABEL = "Public consumer credit data, not Pakistani SME banking data"
MODEL_FEATURES: list[str] = ["loan_to_income", "payment_history_score", "years_in_operation"]

MODEL_NAMES: tuple[str, ...] = ("logistic_regression", "xgboost", "random_forest", "ensemble")
MODEL_LABELS: dict[str, str] = {
    "logistic_regression": "Logistic regression (baseline)",
    "xgboost": "XGBoost alone",
    "random_forest": "Random forest alone",
    "ensemble": "Served ensemble (XGBoost 0.6 + random forest 0.4)",
}

# Calibration: each isotonic level averages at least this many loans.
CALIBRATION_BIN_ROWS = 250
SIGMOID_GRID_POINTS = 201


# --- data -------------------------------------------------------------------------


def file_sha256(path: Path) -> str:
    """SHA-256 of a file's bytes: the dataset identifier for reproducibility."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ids_sha256(index) -> str:
    """Order-independent SHA-256 of a set of row ids."""
    joined = ",".join(str(int(value)) for value in sorted(index))
    return hashlib.sha256(joined.encode("ascii")).hexdigest()


@dataclass
class Prepared:
    """The modelling frame, the raw rows behind it and what was excluded."""

    frame: pd.DataFrame  # MODEL_FEATURES + TARGET, indexed by original row number
    raw: pd.DataFrame  # the same rows, every original column
    dataset_sha256: str | None
    rows_in_file: int
    excluded: dict[str, int] = field(default_factory=dict)


def prepare_frame(raw_file: pd.DataFrame, dataset_sha256: str | None = None) -> Prepared:
    """Drop exact duplicates and map the consumer file onto ForiFlow features.

    Exact duplicate rows are dropped before the split: left in, a copy could
    sit in training and its twin in the test set, which is a leak. Nothing is
    learned here; missing values stay missing until the training split is known.
    """
    from ml.train_real_model import map_credit_risk

    raw = raw_file.reset_index(drop=True)
    duplicated = raw.duplicated(keep="first")
    kept = raw.loc[~duplicated].copy()
    kept.index.name = "row_id"
    mapped = map_credit_risk(kept)[MODEL_FEATURES + [TARGET]]
    return Prepared(
        frame=mapped,
        raw=kept,
        dataset_sha256=dataset_sha256,
        rows_in_file=int(len(raw)),
        excluded={"exact_duplicate_rows": int(duplicated.sum())},
    )


def load_prepared(path: Path | None = None) -> Prepared:
    """Read the training file and prepare it."""
    path = path or DATA_DIR / DATASET_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Expected dataset at {path}. See backend/README.md, 'Training data'."
        )
    return prepare_frame(pd.read_csv(path), dataset_sha256=file_sha256(path))


@dataclass(frozen=True)
class Split:
    """Row ids of the three sets."""

    train: pd.Index
    validation: pd.Index
    test: pd.Index
    seed: int

    def describe(self, frame: pd.DataFrame) -> dict:
        y = frame[TARGET]
        return {
            "method": (
                "stratified on the default flag: 20% final test set first, then 25% of "
                "the rest as validation (20% of the file), the remaining 60% as training"
            ),
            "seed": self.seed,
            "fractions": {
                "train": 1 - FINAL_TEST_FRACTION - VALIDATION_FRACTION,
                "validation": VALIDATION_FRACTION,
                "final_test": FINAL_TEST_FRACTION,
            },
            "rows": {
                "train": int(len(self.train)),
                "validation": int(len(self.validation)),
                "final_test": int(len(self.test)),
            },
            "default_rate": {
                "train": float(y.loc[self.train].mean()),
                "validation": float(y.loc[self.validation].mean()),
                "final_test": float(y.loc[self.test].mean()),
            },
            "id_sha256": {
                "train": ids_sha256(self.train),
                "validation": ids_sha256(self.validation),
                "final_test": ids_sha256(self.test),
            },
            "uses": {
                "train": "imputation medians, clip bounds, scaler, SMOTE, model fitting, 5-fold CV",
                "validation": "calibration method choice and fit; baseline comparison",
                "final_test": "one final evaluation only; nothing is chosen or tuned on it",
            },
        }


def split_rows(frame: pd.DataFrame, seed: int = SEED) -> Split:
    """Stratified train / validation / final-test split of the row ids."""
    y = frame[TARGET]
    rest, test = train_test_split(
        frame.index, test_size=FINAL_TEST_FRACTION, stratify=y, random_state=seed
    )
    validation_share = VALIDATION_FRACTION / (1.0 - FINAL_TEST_FRACTION)
    train, validation = train_test_split(
        rest, test_size=validation_share, stratify=y.loc[rest], random_state=seed
    )
    return Split(
        train=pd.Index(sorted(train)),
        validation=pd.Index(sorted(validation)),
        test=pd.Index(sorted(test)),
        seed=seed,
    )


# --- preprocessing ------------------------------------------------------------------


class TrainOnlyPreprocessor(BaseEstimator, TransformerMixin):
    """Median imputation then 1st/99th percentile clipping, learned in ``fit`` only.

    Inside a pipeline this is fitted on the training rows (or the training part
    of a CV fold) and merely applied to anything else, so no statistic of a
    validation, test or held-out fold reaches the model.
    """

    def __init__(self, clip_quantiles: tuple[float, float] = CLIP_QUANTILES) -> None:
        self.clip_quantiles = clip_quantiles

    def _frame(self, X) -> pd.DataFrame:
        if isinstance(X, pd.DataFrame):
            return X.copy()
        columns = getattr(self, "columns_", None)
        return pd.DataFrame(np.asarray(X, dtype=float), columns=columns)

    def fit(self, X, y=None) -> "TrainOnlyPreprocessor":
        frame = self._frame(X)
        self.columns_ = list(frame.columns)
        self.medians_ = {column: float(frame[column].median()) for column in self.columns_}
        filled = frame.fillna(self.medians_)
        low_q, high_q = self.clip_quantiles
        self.clips_ = {}
        for column in self.columns_:
            low, high = float(filled[column].quantile(low_q)), float(filled[column].quantile(high_q))
            self.clips_[column] = [low, high if high > low else low + 1e-6]
        self.n_fit_rows_ = int(len(frame))
        return self

    def transform(self, X) -> np.ndarray:
        frame = self._frame(X)[self.columns_].fillna(self.medians_)
        for column, (low, high) in self.clips_.items():
            frame[column] = frame[column].clip(low, high)
        return frame.to_numpy(dtype=float)


def build_estimator(name: str, features: list[str]):
    """One of the compared learners, configured exactly as in production."""
    from ml.train_real_model import build_ensemble

    if name == "logistic_regression":
        return LogisticRegression(max_iter=1000, random_state=SEED)
    ensemble = build_ensemble(features)
    if name == "ensemble":
        return ensemble
    members = dict(ensemble.estimators)
    if name == "xgboost":
        return members["xgb"]
    if name == "random_forest":
        return members["rf"]
    raise ValueError(f"Unknown model {name!r}")


def build_training_pipeline(name: str, features: list[str]) -> ImbPipeline:
    """Preprocess, scale, SMOTE, fit. imblearn applies SMOTE in ``fit`` only."""
    return ImbPipeline(
        steps=[
            ("preprocess", TrainOnlyPreprocessor()),
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=SEED, k_neighbors=5)),
            ("model", build_estimator(name, features)),
        ]
    )


# --- metrics -------------------------------------------------------------------------


def classification_metrics(
    y: np.ndarray, probability: np.ndarray, threshold: float = EVALUATION_THRESHOLD
) -> dict:
    """Discrimination, calibration and the confusion matrix at a stated threshold."""
    y = np.asarray(y).astype(int)
    probability = np.asarray(probability, dtype=float)
    flagged = probability >= threshold
    tp = int((flagged & (y == 1)).sum())
    fp = int((flagged & (y == 0)).sum())
    fn = int((~flagged & (y == 1)).sum())
    tn = int((~flagged & (y == 0)).sum())
    return {
        "rows": int(len(y)),
        "positives": int(y.sum()),
        "auc_roc": float(roc_auc_score(y, probability)),
        "pr_auc": float(average_precision_score(y, probability)),
        "brier": float(brier_score_loss(y, probability)),
        "threshold": float(threshold),
        "precision": float(precision_score(y, flagged, zero_division=0)),
        "recall": float(recall_score(y, flagged, zero_division=0)),
        "f1": float(f1_score(y, flagged, zero_division=0)),
        "accuracy": float((tp + tn) / len(y)),
        "mean_predicted": float(probability.mean()),
        "confusion": {"true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn},
    }


def cross_validate_training(
    name: str, X: pd.DataFrame, y: pd.Series, folds: int = CV_FOLDS
) -> dict:
    """Stratified k-fold CV on the training split only; everything refit per fold."""
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=SEED)
    per_fold = []
    for fit_index, score_index in splitter.split(X, y):
        pipeline = build_training_pipeline(name, list(X.columns))
        pipeline.fit(X.iloc[fit_index], y.iloc[fit_index])
        probability = pipeline.predict_proba(X.iloc[score_index])[:, 1]
        metrics = classification_metrics(y.iloc[score_index].to_numpy(), probability)
        per_fold.append({key: metrics[key] for key in ("auc_roc", "pr_auc", "f1", "brier")})
    summary = {
        f"{key}_mean": float(np.mean([fold[key] for fold in per_fold]))
        for key in ("auc_roc", "pr_auc", "f1", "brier")
    }
    summary["auc_roc_std"] = float(np.std([fold["auc_roc"] for fold in per_fold]))
    summary["per_fold"] = per_fold
    summary["folds"] = folds
    return summary


def paired_auc_test(candidate: list[float], reference: list[float]) -> dict:
    """Paired t-test over CV folds. Folds share training rows, so approximate."""
    from scipy import stats

    difference = np.asarray(candidate) - np.asarray(reference)
    if np.allclose(difference, 0.0):
        return {"mean_auc_difference": 0.0, "paired_t_test_p": 1.0}
    result = stats.ttest_rel(candidate, reference)
    return {
        "mean_auc_difference": float(difference.mean()),
        "paired_t_test_p": float(result.pvalue),
    }


# --- calibration --------------------------------------------------------------------


def fit_isotonic_binned(raw: np.ndarray, y: np.ndarray) -> tuple[list[float], list[float]]:
    """Isotonic regression over equal-size bins of the raw probability."""
    from sklearn.isotonic import IsotonicRegression

    order = np.argsort(raw, kind="stable")
    bins = np.array_split(order, max(len(raw) // CALIBRATION_BIN_ROWS, 2))
    centres = np.array([raw[chunk].mean() for chunk in bins])
    rates = np.array([y[chunk].mean() for chunk in bins])
    weights = np.array([len(chunk) for chunk in bins], dtype=float)
    model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    model.fit(centres, rates, sample_weight=weights)
    return [float(v) for v in model.X_thresholds_], [float(v) for v in model.y_thresholds_]


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def fit_sigmoid(raw: np.ndarray, y: np.ndarray) -> tuple[list[float], list[float]]:
    """Platt scaling on the logit of the raw probability, stored as breakpoints."""
    model = LogisticRegression(C=1e6, max_iter=1000)
    model.fit(_logit(raw).reshape(-1, 1), y)
    grid = np.linspace(0.0, 1.0, SIGMOID_GRID_POINTS)
    calibrated = model.predict_proba(_logit(grid).reshape(-1, 1))[:, 1]
    return [float(v) for v in grid], [float(v) for v in calibrated]


CALIBRATORS = {"isotonic": fit_isotonic_binned, "sigmoid": fit_sigmoid}


def apply_breakpoints(raw: np.ndarray, x: list[float], y: list[float]) -> np.ndarray:
    """What serving does: linear interpolation between breakpoints, clipped."""
    return np.interp(np.asarray(raw, dtype=float), x, y)


def select_calibration(raw: np.ndarray, y: np.ndarray, seed: int = SEED) -> dict:
    """Choose a calibrator on the validation set by cross-fitting, then fit it there.

    Each method is fitted on 4/5 of the validation rows and scored (Brier) on
    the remaining fifth, five times. The lower out-of-fold Brier wins, and is
    kept only if it beats the uncalibrated probability. The final test set is
    not involved.
    """
    y = np.asarray(y).astype(int)
    raw = np.asarray(raw, dtype=float)
    splitter = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=seed)
    out_of_fold = {name: np.zeros(len(raw)) for name in CALIBRATORS}
    for fit_index, score_index in splitter.split(raw.reshape(-1, 1), y):
        for name, fitter in CALIBRATORS.items():
            x_points, y_points = fitter(raw[fit_index], y[fit_index])
            out_of_fold[name][score_index] = apply_breakpoints(raw[score_index], x_points, y_points)
    briers = {"none": float(brier_score_loss(y, raw))}
    briers.update({name: float(brier_score_loss(y, values)) for name, values in out_of_fold.items()})
    best = min(CALIBRATORS, key=lambda name: briers[name])
    chosen = best if briers[best] < briers["none"] else None
    x_points, y_points = CALIBRATORS[chosen](raw, y) if chosen else ([], [])
    return {
        "method": chosen,
        "method_label": {
            "isotonic": f"isotonic regression over bins of {CALIBRATION_BIN_ROWS} loans",
            "sigmoid": "Platt (sigmoid) scaling on the logit of the raw probability",
            None: "none",
        }[chosen],
        "selection": {
            "criterion": "out-of-fold Brier score, 5-fold cross-fit within the validation set",
            "brier_out_of_fold": briers,
        },
        "fitted_on": {"set": "validation", "rows": int(len(raw))},
        "raw_probability": x_points,
        "calibrated_probability": y_points,
        "out_of_fold_calibrated": out_of_fold.get(chosen) if chosen else None,
        "display_only": True,
        "note": (
            "Maps the raw ensemble probability to an observed default rate of the public "
            "file. Display only: the score stays 100 x (1 - raw probability) and SHAP "
            "explains the raw probability."
        ),
    }


# --- reliability ------------------------------------------------------------------


def reliability(probability: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    """Predicted against observed default rate in equal-size bins."""
    order = np.argsort(probability, kind="stable")
    rows = []
    for chunk in np.array_split(order, bins):
        if len(chunk):
            rows.append(
                {
                    "predicted": float(np.asarray(probability)[chunk].mean()),
                    "observed": float(np.asarray(y)[chunk].mean()),
                    "rows": int(len(chunk)),
                }
            )
    return rows


def expected_calibration_error(probability: np.ndarray, y: np.ndarray) -> float:
    rows = reliability(probability, y)
    return float(sum(abs(r["predicted"] - r["observed"]) * r["rows"] for r in rows) / len(y))
