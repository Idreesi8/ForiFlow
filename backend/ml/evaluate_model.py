"""Evaluate the served model ONCE on the untouched final test set.

Run from the ``backend`` directory, after ``python -m ml.train_real_model``::

    python -m ml.evaluate_model

Since 2.2 (see :mod:`ml.pipeline`):

1. Rebuild the train / validation / final-test split from the file and the
   seed, and refuse to go on unless the row-id fingerprints match the ones the
   training run recorded.
2. Refuse to run twice for the same trained model (``--force`` overrides and
   says so in the output). The final test set is for one final measurement.
3. Score the final test rows exactly as serving does: training-split medians
   and clip bounds from the metadata, then the scaler and the ensemble.
4. Record discrimination and calibration of the raw and the calibrated
   probability, the confusion matrix at the model evaluation threshold, the
   baselines (refitted on the training split, deterministic), the Subgroup
   Performance Analysis, and drift reference distributions from the training
   and validation splits (not from the test set).

Nothing is chosen here: the calibrator, the evaluation threshold and the
model were all fixed before this script reads a single test row. The score
cut-offs in the tables are model evaluation cut-offs (equal to the demo policy
v1.0 values) and say nothing about the credit policy in force.
"""

from __future__ import annotations

import argparse
import json
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score, roc_curve

from ml.features import (
    COMPARISON_PATH,
    EVALUATION_PATH,
    FAIRNESS_PATH,
    MODEL_PATH,
    SCALER_PATH,
    apply_clips,
    load_feature_metadata,
    load_model_evaluation,
)

# Model evaluation cut-offs on the 0-100 score: the demo policy v1.0 values,
# fixed for comparability across releases. Not the credit policy in force.
REJECT_UPPER_BOUND = 40.0
MANUAL_REVIEW_UPPER_BOUND = 70.0
RELIABILITY_BINS = 10
ROC_POINTS = 120
# Score cut-offs shown in the threshold table: "flag everything at or below".
THRESHOLD_SCORES = (30.0, 40.0, 50.0, 60.0, 70.0)

# Bins for the drift monitor (services.drift_service). A value falls in the bin
# whose lower edge it reaches; the last bin has no upper limit.
DRIFT_BINS: dict[str, tuple[list[float], list[str]]] = {
    "risk_score": (
        [0, 20.01, 40.01, 55.01, 70.01, 85.01],
        ["0-20", "20-40", "40-55", "55-70", "70-85", "85-100"],
    ),
    "loan_to_income": (
        [0, 0.1, 0.2, 0.3, 0.4],
        ["under 10%", "10-20%", "20-30%", "30-40%", "40% or more"],
    ),
    "payment_history_score": ([0, 52.5], ["adverse", "clean"]),
    "years_in_operation": (
        [0, 2, 4, 7, 11],
        ["under 2", "2-3", "4-6", "7-10", "11 or more"],
    ),
}


class AlreadyEvaluated(RuntimeError):
    """The final test set was already used for this trained model."""


class SplitMismatch(RuntimeError):
    """The rebuilt split is not the one the model was trained with."""


def bin_shares(values: np.ndarray, edges: list[float]) -> list[float]:
    """Share of ``values`` in each bin defined by its lower ``edges``."""
    index = np.searchsorted(np.asarray(edges, dtype=float), values, side="right") - 1
    counts = np.bincount(np.clip(index, 0, len(edges) - 1), minlength=len(edges))
    return [float(count / len(values)) for count in counts]


def reliability(probabilities: np.ndarray, y: np.ndarray) -> list[dict]:
    """Predicted against observed default rate in equal-size bins."""
    from ml.pipeline import reliability as _reliability

    return _reliability(probabilities, y, RELIABILITY_BINS)


def expected_calibration_error(probabilities: np.ndarray, y: np.ndarray) -> float:
    from ml.pipeline import expected_calibration_error as _ece

    return _ece(probabilities, y)


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


def band_table(scores: np.ndarray, calibrated: np.ndarray | None, y: np.ndarray) -> list[dict]:
    """Observed (and calibrated) default rate inside each evaluation band."""
    bands = (
        ("Rejected", scores <= REJECT_UPPER_BOUND),
        ("Manual Review", (scores > REJECT_UPPER_BOUND) & (scores <= MANUAL_REVIEW_UPPER_BOUND)),
        ("Approved", scores > MANUAL_REVIEW_UPPER_BOUND),
    )
    return [
        {
            "band": name,
            "rows": int(mask.sum()),
            "share": float(mask.mean()),
            "observed_default_rate": float(y[mask].mean()) if mask.any() else None,
            "calibrated_pd": (
                float(calibrated[mask].mean()) if calibrated is not None and mask.any() else None
            ),
        }
        for name, mask in bands
    ]


def roc_points(probabilities: np.ndarray, y: np.ndarray) -> list[dict]:
    """The ROC curve, thinned to a size a chart can draw."""
    fpr, tpr, _ = roc_curve(y, probabilities)
    keep = np.unique(np.linspace(0, len(fpr) - 1, ROC_POINTS).round().astype(int))
    return [{"fpr": float(fpr[i]), "tpr": float(tpr[i])} for i in keep]


def serving_features(X: pd.DataFrame, metadata: dict) -> np.ndarray:
    """Rows transformed exactly as training fitted and serving applies them."""
    medians = metadata.get("feature_medians", {})
    clips = metadata.get("feature_clips", {})
    filled = X.fillna(medians)
    rows = [apply_clips(row, clips) for row in filled.to_dict("records")]
    return np.array([[row[name] for name in metadata["feature_names"]] for row in rows], dtype=float)


def check_split(split_info: dict, metadata: dict) -> None:
    recorded = metadata.get("split", {}).get("id_sha256")
    if not recorded:
        raise SplitMismatch("The metadata records no split; retrain with ml.train_real_model (2.2).")
    if recorded != split_info["id_sha256"]:
        raise SplitMismatch(
            "The rebuilt split does not match the training run's (different file, seed or code)."
        )


def guard_single_use(metadata: dict, existing: dict | None, force: bool) -> None:
    if (
        existing
        and existing.get("model_trained_at") == metadata.get("trained_at")
        and existing.get("final_test")
        and not force
    ):
        raise AlreadyEvaluated(
            f"The final test set was already evaluated for the model trained at "
            f"{metadata.get('trained_at')} (recorded {existing.get('recorded_at')}). It is "
            "measured once. Use --force only to regenerate the same figures."
        )


def evaluate(force: bool = False) -> dict:
    """Run the one final evaluation and write the JSON files."""
    from ml import pipeline
    from ml.fairness_audit import subgroup_analysis

    metadata = load_feature_metadata()
    guard_single_use(metadata, load_model_evaluation(), force)
    features = metadata["feature_names"]

    prepared = pipeline.load_prepared()
    if metadata.get("dataset_sha256") and prepared.dataset_sha256 != metadata["dataset_sha256"]:
        raise SplitMismatch("The training file changed since the model was trained (SHA-256 differs).")
    frame = prepared.frame
    split = pipeline.split_rows(frame, seed=int(metadata.get("random_seed", pipeline.SEED)))
    split_info = split.describe(frame)
    check_split(split_info, metadata)

    X_train, y_train = frame.loc[split.train, features], frame.loc[split.train, pipeline.TARGET]
    X_val, y_val = frame.loc[split.validation, features], frame.loc[split.validation, pipeline.TARGET]
    X_test, y_test = frame.loc[split.test, features], frame.loc[split.test, pipeline.TARGET]
    y_test_arr = y_test.to_numpy()

    model = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)

    def served_pd(X: pd.DataFrame) -> np.ndarray:
        return model.predict_proba(scaler.transform(serving_features(X, metadata)))[:, 1]

    calibration = metadata.get("calibration", {})
    breakpoints = (calibration.get("raw_probability"), calibration.get("calibrated_probability"))
    has_calibrator = bool(breakpoints[0])

    # --- the one read of the final test set -------------------------------------
    raw_pd = served_pd(X_test)
    calibrated_pd = pipeline.apply_breakpoints(raw_pd, *breakpoints) if has_calibrator else None
    scores = 100.0 * (1.0 - raw_pd)
    base_rate = float(y_train.mean())
    raw_metrics = pipeline.classification_metrics(y_test_arr, raw_pd)

    final_test = {
        "rows": int(len(y_test_arr)),
        "default_rate": float(y_test_arr.mean()),
        "evaluation_threshold": pipeline.EVALUATION_THRESHOLD,
        "metrics_raw": raw_metrics,
        "metrics_calibrated": (
            pipeline.classification_metrics(y_test_arr, calibrated_pd) if has_calibrator else None
        ),
        "raw": summary(raw_pd, y_test_arr),
        "calibrated": summary(calibrated_pd, y_test_arr) if has_calibrator else None,
        "brier_no_skill": float(brier_score_loss(y_test_arr, np.full(len(y_test_arr), base_rate))),
        "roc_curve": roc_points(raw_pd, y_test_arr),
        "confusion_at_half": confusion(raw_pd >= pipeline.EVALUATION_THRESHOLD, y_test_arr),
        "thresholds": [
            {"flag_score_at_or_below": cut, **confusion(scores <= cut, y_test_arr)}
            for cut in THRESHOLD_SCORES
        ],
        "bands": band_table(scores, calibrated_pd, y_test_arr),
        "reliability_raw": reliability(raw_pd, y_test_arr),
        "reliability_calibrated": (
            reliability(calibrated_pd, y_test_arr) if has_calibrator else None
        ),
    }

    # Baselines: refitted on the training split with the same seeds; their
    # validation figures must reproduce the training run's exactly.
    baselines = {}
    recorded_validation = metadata.get("validation", {}).get("baselines", {})
    for name in pipeline.MODEL_NAMES:
        if name == "ensemble":
            test_pd = raw_pd
            validation_auc = float(roc_auc_score(y_val, served_pd(X_val)))
        else:
            fitted = pipeline.build_training_pipeline(name, features).fit(X_train, y_train)
            test_pd = fitted.predict_proba(X_test)[:, 1]
            validation_auc = float(roc_auc_score(y_val, fitted.predict_proba(X_val)[:, 1]))
        recorded = recorded_validation.get(name, {}).get("auc_roc")
        baselines[name] = {
            "label": pipeline.MODEL_LABELS[name],
            "final_test": pipeline.classification_metrics(y_test_arr, test_pd),
            "validation_auc_reproduced": validation_auc,
            "validation_auc_recorded": recorded,
            "reproduced": recorded is None or abs(validation_auc - recorded) < 1e-6,
        }
    ensemble_auc = baselines["ensemble"]["final_test"]["auc_roc"]
    for name, row in baselines.items():
        row["auc_gap_to_ensemble"] = row["final_test"]["auc_roc"] - ensemble_auc

    # Drift reference: inputs of the training split, scores of the validation
    # split (out-of-sample, and not the test set).
    val_scores = 100.0 * (1.0 - served_pd(X_val))
    train_inputs = pd.DataFrame(serving_features(X_train, metadata), columns=features)
    reference = {
        name: {
            "edges": edges,
            "labels": labels,
            "shares": bin_shares(
                val_scores if name == "risk_score" else train_inputs[name].to_numpy(dtype=float),
                edges,
            ),
            "rows": int(len(val_scores) if name == "risk_score" else len(train_inputs)),
            "source": (
                "validation split scores" if name == "risk_score" else "training split inputs"
            ),
        }
        for name, (edges, labels) in DRIFT_BINS.items()
        if name == "risk_score" or name in features
    }

    subgroups = subgroup_analysis(
        prepared.raw.loc[split.test],
        prepared.raw.loc[split.train],
        raw_pd,
        calibrated_pd if has_calibrator else raw_pd,
        y_test_arr,
        dataset=metadata["dataset"],
        trained_at=metadata.get("trained_at"),
    )

    payload = {
        "dataset": metadata["dataset"],
        "dataset_type_label": metadata.get("dataset_type_label"),
        "model_trained_at": metadata.get("trained_at"),
        "protocol": (
            "2.2 protocol: stratified 60/20/20 train / validation / final-test split "
            f"(seed {split.seed}); medians, clip bounds, scaler and SMOTE fitted on the "
            "training split only; calibrator chosen and fitted on the validation split; "
            "every figure below is the served model on the final test set, measured once."
        ),
        "split": split_info,
        "rows": {
            "train": split_info["rows"]["train"],
            "validation": split_info["rows"]["validation"],
            "final_test": split_info["rows"]["final_test"],
            # Pre-2.2 name for the evaluated set, kept for older clients.
            "holdout": split_info["rows"]["final_test"],
        },
        "default_rate": {
            "train": base_rate,
            "validation": float(y_val.mean()),
            "final_test": float(y_test_arr.mean()),
            "holdout": float(y_test_arr.mean()),
        },
        "feature_correlation_spearman": {
            f"{a} ~ {b}": float(X_train[a].corr(X_train[b], method="spearman"))
            for i, a in enumerate(features)
            for b in features[i + 1 :]
        },
        "evaluation_thresholds": {
            "raw_probability": pipeline.EVALUATION_THRESHOLD,
            "score_cutoffs": list(THRESHOLD_SCORES),
            "band_cutoffs": {"decline_max_score": REJECT_UPPER_BOUND, "manual_review_max_score": MANUAL_REVIEW_UPPER_BOUND},
            "note": (
                "Model evaluation thresholds, fixed in advance (the band cut-offs equal "
                "demo policy v1.0). They are not the credit policy in force and were not "
                "optimised on any data."
            ),
        },
        "reference_distributions": reference,
        "reference_note": "Reference / demo distribution: the public training file, not a bank portfolio.",
        "calibrator": {
            "method": calibration.get("method_label"),
            "raw_probability": breakpoints[0] or [],
            "calibrated_probability": breakpoints[1] or [],
            "fitted_on": calibration.get("fitted_on"),
            "selection": calibration.get("selection"),
            "display_only": True,
        },
        "validation": metadata.get("validation"),
        "final_test": final_test,
        # Pre-2.2 name, kept for older clients: the same final-test figures.
        "holdout": final_test,
        "baselines": baselines,
        "previous_model": metadata.get("previous_model"),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    EVALUATION_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    FAIRNESS_PATH.write_text(json.dumps(subgroups, indent=2), encoding="utf-8")

    if COMPARISON_PATH.exists():
        comparison = json.loads(COMPARISON_PATH.read_text(encoding="utf-8"))
        if comparison.get("model_trained_at") == metadata.get("trained_at"):
            for name, row in baselines.items():
                key = "served_ensemble_xgb_rf" if name == "ensemble" else name
                if key in comparison["models"]:
                    comparison["models"][key]["final_test"] = row["final_test"]
                    comparison["models"][key]["auc_gap_to_ensemble_final_test"] = row["auc_gap_to_ensemble"]
            comparison["final_test_rows"] = final_test["rows"]
            COMPARISON_PATH.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Regenerate an existing final evaluation.")
    args = parser.parse_args(argv)
    payload = evaluate(force=args.force)
    test = payload["final_test"]
    print(f"\nFinal test set: {test['rows']:,} rows, default rate {test['default_rate']:.4f}")
    for name in ("raw", "calibrated"):
        row = test[name]
        if row:
            print(
                f"  {name:<11} AUC {row['auc_roc']:.4f}  Brier {row['brier']:.4f}  "
                f"ECE {row['expected_calibration_error']:.4f}  mean PD {row['mean_predicted']:.4f}"
            )
    print(f"  no-skill Brier {test['brier_no_skill']:.4f}")
    for name, row in payload["baselines"].items():
        m = row["final_test"]
        print(
            f"  {name:<20} AUC {m['auc_roc']:.4f} PR-AUC {m['pr_auc']:.4f} F1 {m['f1']:.4f} "
            f"Brier {m['brier']:.4f} reproduced={row['reproduced']}"
        )
    print(f"\nwrote {EVALUATION_PATH.name}, {FAIRNESS_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
