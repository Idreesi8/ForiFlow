"""Calibrate the served ensemble and measure it on the untouched hold-out.

Run from the ``backend`` directory::

    python -m ml.evaluate_model

The served model is trained on SMOTE-balanced data, so its raw probability
assumes half of all loans default. That keeps the ranking (AUC) intact but makes
the number itself too high. This script fixes that without touching the model:

1. Rebuild the exact 80 / 20 split used by :mod:`ml.train_real_model`.
2. On the 80% training part only, collect out-of-fold predictions (5 folds,
   scaler + SMOTE fitted inside each fold) and fit an isotonic regression that
   maps the raw probability to the observed default rate. It is fitted over
   bins of 250 loans, so no reported probability rests on a handful of loans.
3. Apply the served model plus that calibrator to the 20% hold-out, which
   neither of them has seen, and record ROC, confusion matrix, threshold
   trade-offs, reliability and the default rate inside each policy band.

Results are written to ``ml/model_evaluation.json``. The calibrator is stored
there as plain breakpoints, so serving needs no extra pickle. Nothing here
changes the served model, the score or the policy bands.
"""

from __future__ import annotations

import json
import time

import joblib
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score, roc_curve
from sklearn.model_selection import StratifiedKFold, train_test_split

from ml.features import EVALUATION_PATH, MODEL_PATH, SCALER_PATH, load_feature_metadata
from ml.train_real_model import (
    N_SPLITS,
    RANDOM_STATE,
    TARGET,
    build_candidates,
    build_pipeline,
    load_datasets,
    map_credit_risk,
)

# Policy bands on the 0-100 score, mirrored from services.scoring_service.
REJECT_UPPER_BOUND = 40.0
MANUAL_REVIEW_UPPER_BOUND = 70.0
# Loans averaged into each calibration bin; no reported PD rests on fewer.
CALIBRATION_BIN_ROWS = 250
RELIABILITY_BINS = 10
ROC_POINTS = 120
# Score cut-offs shown in the threshold table: "flag everything at or below".
THRESHOLD_SCORES = (30.0, 40.0, 50.0, 60.0, 70.0)


def expected_calibration_error(probabilities: np.ndarray, y: np.ndarray) -> float:
    """Mean gap between predicted and observed default rate over equal-size bins."""
    return float(
        sum(
            abs(row["predicted"] - row["observed"]) * row["rows"] / len(y)
            for row in reliability(probabilities, y)
        )
    )


def reliability(probabilities: np.ndarray, y: np.ndarray) -> list[dict]:
    """Predicted against observed default rate in equal-size bins."""
    order = np.argsort(probabilities, kind="stable")
    rows = []
    for chunk in np.array_split(order, RELIABILITY_BINS):
        if len(chunk) == 0:
            continue
        rows.append(
            {
                "predicted": float(probabilities[chunk].mean()),
                "observed": float(y[chunk].mean()),
                "rows": int(len(chunk)),
            }
        )
    return rows


def summary(probabilities: np.ndarray, y: np.ndarray) -> dict:
    """Discrimination and calibration of one set of probabilities."""
    return {
        "auc_roc": float(roc_auc_score(y, probabilities)),
        "brier": float(brier_score_loss(y, probabilities)),
        "expected_calibration_error": expected_calibration_error(probabilities, y),
        "mean_predicted": float(probabilities.mean()),
    }


def confusion(flagged: np.ndarray, y: np.ndarray) -> dict:
    """Class-wise results when ``flagged`` rows are treated as predicted defaults."""
    tp = int((flagged & (y == 1)).sum())
    fp = int((flagged & (y == 0)).sum())
    fn = int((~flagged & (y == 1)).sum())
    tn = int((~flagged & (y == 0)).sum())
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "recall_default": tp / (tp + fn) if tp + fn else 0.0,
        "recall_non_default": tn / (tn + fp) if tn + fp else 0.0,
        "precision_default": tp / (tp + fp) if tp + fp else 0.0,
        "accuracy": (tp + tn) / len(y),
    }


def band_table(scores: np.ndarray, calibrated: np.ndarray, y: np.ndarray) -> list[dict]:
    """Observed and calibrated default rate inside each policy band."""
    bands = (
        ("Rejected", scores <= REJECT_UPPER_BOUND),
        (
            "Manual Review",
            (scores > REJECT_UPPER_BOUND) & (scores <= MANUAL_REVIEW_UPPER_BOUND),
        ),
        ("Approved", scores > MANUAL_REVIEW_UPPER_BOUND),
    )
    return [
        {
            "band": name,
            "rows": int(mask.sum()),
            "share": float(mask.mean()),
            "observed_default_rate": float(y[mask].mean()) if mask.any() else None,
            "calibrated_pd": float(calibrated[mask].mean()) if mask.any() else None,
        }
        for name, mask in bands
    ]


def roc_points(probabilities: np.ndarray, y: np.ndarray) -> list[dict]:
    """The ROC curve, thinned to a size a chart can draw."""
    fpr, tpr, _ = roc_curve(y, probabilities)
    keep = np.unique(np.linspace(0, len(fpr) - 1, ROC_POINTS).round().astype(int))
    return [{"fpr": float(fpr[i]), "tpr": float(tpr[i])} for i in keep]


def fit_calibrator(raw: np.ndarray, y: np.ndarray) -> IsotonicRegression:
    """Isotonic regression over equal-size bins of the raw probability.

    Fitted row by row, isotonic regression ends in tiny blocks at both extremes
    and reports a probability of exactly 0% or 100% from a handful of loans.
    Averaging :data:`CALIBRATION_BIN_ROWS` loans per bin first means every level
    of the calibrator is the default rate of at least that many loans.
    """
    order = np.argsort(raw, kind="stable")
    bins = np.array_split(order, max(len(raw) // CALIBRATION_BIN_ROWS, 2))
    centres = np.array([raw[chunk].mean() for chunk in bins])
    rates = np.array([y[chunk].mean() for chunk in bins])
    weights = np.array([len(chunk) for chunk in bins], dtype=float)

    calibrator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    calibrator.fit(centres, rates, sample_weight=weights)
    return calibrator


def main() -> int:
    """Fit the calibrator, evaluate on the hold-out and write the JSON."""
    metadata = load_feature_metadata()
    features = metadata["feature_names"]

    raw = load_datasets(("credit_risk",))
    mapped = {"credit_risk": map_credit_risk(raw["credit_risk"])}
    winner = next(c for c in build_candidates(mapped) if c.name == metadata["dataset"])
    X, y = winner.frame[features], winner.frame[TARGET]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE
    )
    y_train_arr, y_test_arr = y_train.to_numpy(), y_test.to_numpy()

    # Out-of-fold predictions on the training part: every row is predicted by a
    # model that never saw it, which is what the served model does in production.
    out_of_fold = np.zeros(len(X_train))
    splitter = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    for fit_index, predict_index in splitter.split(X_train, y_train):
        pipeline = build_pipeline(features)
        pipeline.fit(X_train.iloc[fit_index], y_train.iloc[fit_index])
        out_of_fold[predict_index] = pipeline.predict_proba(X_train.iloc[predict_index])[:, 1]

    calibrator = fit_calibrator(out_of_fold, y_train_arr)

    model = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
    raw_pd = model.predict_proba(scaler.transform(X_test.to_numpy()))[:, 1]
    calibrated_pd = calibrator.predict(raw_pd)
    scores = 100.0 * (1.0 - raw_pd)

    base_rate = float(y_train_arr.mean())
    payload = {
        "dataset": metadata["dataset"],
        "model_trained_at": metadata.get("trained_at"),
        "protocol": (
            "80/20 stratified split (random_state=42), identical to training. "
            f"Calibrator: isotonic regression on {N_SPLITS}-fold out-of-fold "
            "predictions of the training part (scaler + SMOTE inside each fold). "
            "Every figure is the served model on the 20% hold-out."
        ),
        "rows": {"train": int(len(X_train)), "holdout": int(len(X_test))},
        "default_rate": {"train": base_rate, "holdout": float(y_test_arr.mean())},
        # SHAP splits credit between correlated inputs, so low values here mean
        # each attribution can be read on its own.
        "feature_correlation_spearman": {
            f"{a} ~ {b}": float(X_train[a].corr(X_train[b], method="spearman"))
            for i, a in enumerate(features)
            for b in features[i + 1 :]
        },
        "calibrator": {
            "method": f"isotonic over bins of {CALIBRATION_BIN_ROWS} loans",
            "raw_probability": [float(v) for v in calibrator.X_thresholds_],
            "calibrated_probability": [float(v) for v in calibrator.y_thresholds_],
        },
        "holdout": {
            "raw": summary(raw_pd, y_test_arr),
            "calibrated": summary(calibrated_pd, y_test_arr),
            # What a model with no information scores: always predict the base rate.
            "brier_no_skill": float(
                brier_score_loss(y_test_arr, np.full(len(y_test_arr), base_rate))
            ),
            "roc_curve": roc_points(raw_pd, y_test_arr),
            "confusion_at_half": confusion(raw_pd >= 0.5, y_test_arr),
            "thresholds": [
                {"flag_score_at_or_below": cut, **confusion(scores <= cut, y_test_arr)}
                for cut in THRESHOLD_SCORES
            ],
            "bands": band_table(scores, calibrated_pd, y_test_arr),
            "reliability_raw": reliability(raw_pd, y_test_arr),
            "reliability_calibrated": reliability(calibrated_pd, y_test_arr),
        },
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    EVALUATION_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    hold = payload["holdout"]
    print(f"\nHold-out {len(X_test):,} rows, default rate {y_test_arr.mean():.4f}")
    for name in ("raw", "calibrated"):
        row = hold[name]
        print(
            f"  {name:<11} AUC {row['auc_roc']:.4f}  Brier {row['brier']:.4f}  "
            f"ECE {row['expected_calibration_error']:.4f}  mean PD {row['mean_predicted']:.4f}"
        )
    print(f"  no-skill Brier {hold['brier_no_skill']:.4f}")
    for row in hold["bands"]:
        print(
            f"  {row['band']:<14} n={row['rows']:>5}  observed {row['observed_default_rate']:.3f}"
            f"  calibrated {row['calibrated_pd']:.3f}"
        )
    print(f"\nwrote {EVALUATION_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
