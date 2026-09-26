"""Compare the served ensemble against the alternatives it was chosen over.

Run from the ``backend`` directory (LightGBM is optional and only used here)::

    pip install lightgbm        # optional
    python -m ml.compare_models

Every model sees exactly what production sees: the ``credit_risk_shared``
training set built by :mod:`ml.train_real_model` (same imputation and clip
bounds), the same stratified 5-fold split (``shuffle=True, random_state=42``),
and a StandardScaler + SMOTE fitted inside each training fold only. The tree
models carry the production monotone constraints, so the comparison isolates
the choice of learner rather than rewarding a model for breaking them.

Besides discrimination (AUC-ROC, PR-AUC, F1 at 0.5, Brier) it records what the
choice costs at serving time: single-applicant latency, and whether the model
has an exact, fast SHAP explainer.

Results are written to ``ml/model_comparison.json``. Nothing here touches the
served artefacts.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from ml.train_real_model import (
    FEATURE_MONOTONE_CONSTRAINTS,
    N_SPLITS,
    RANDOM_STATE,
    TARGET,
    build_candidates,
    build_ensemble,
    load_datasets,
    map_credit_risk,
)

OUTPUT_PATH = Path(__file__).resolve().parent / "model_comparison.json"
LATENCY_RUNS = 200


def served_members(features: list[str]):
    """The two members exactly as production builds them."""
    ensemble = build_ensemble(features)
    return dict(ensemble.estimators)


def candidates(features: list[str]) -> dict[str, dict]:
    """Every learner under comparison, with what it offers for explanation."""
    constraints = [FEATURE_MONOTONE_CONSTRAINTS[name] for name in features]
    members = served_members(features)
    models: dict[str, dict] = {
        "logistic_regression": {
            "model": LogisticRegression(max_iter=1000),
            "explainer": "exact (linear coefficients)",
            "monotone": "yes, by construction (one sign per feature)",
        },
        "xgboost_only": {
            "model": members["xgb"],
            "explainer": "exact TreeSHAP",
            "monotone": "yes (monotone_constraints)",
        },
        "random_forest_only": {
            "model": members["rf"],
            "explainer": "exact TreeSHAP",
            "monotone": "yes (monotonic_cst)",
        },
        "served_ensemble_xgb_rf": {
            "model": build_ensemble(features),
            "explainer": "exact TreeSHAP per member, weighted",
            "monotone": "yes (both members constrained)",
        },
        "mlp_neural_network": {
            "model": MLPClassifier(
                hidden_layer_sizes=(32, 16),
                max_iter=300,
                early_stopping=True,
                random_state=RANDOM_STATE,
            ),
            "explainer": "no exact explainer; KernelSHAP (sampled, slow)",
            "monotone": "no (not constrainable in scikit-learn)",
        },
    }
    try:
        from lightgbm import LGBMClassifier

        models["lightgbm"] = {
            "model": LGBMClassifier(
                n_estimators=300,
                max_depth=5,
                learning_rate=0.08,
                num_leaves=31,
                monotone_constraints=constraints,
                random_state=RANDOM_STATE,
                verbose=-1,
            ),
            "explainer": "exact TreeSHAP",
            "monotone": "yes (monotone_constraints)",
        }
    except ImportError:
        print("lightgbm not installed; skipping it (pip install lightgbm).")
    return models


def evaluate(name: str, spec: dict, X: pd.DataFrame, y: pd.Series) -> dict:
    """Stratified 5-fold CV with scaling and SMOTE inside each training fold."""
    splitter = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    folds = []
    last_pipeline = None
    last_test = None
    for train_index, test_index in splitter.split(X, y):
        pipeline = ImbPipeline(
            steps=[
                ("scaler", StandardScaler()),
                ("smote", SMOTE(random_state=RANDOM_STATE, k_neighbors=5)),
                ("model", _fresh(spec["model"])),
            ]
        )
        started = time.perf_counter()
        pipeline.fit(X.iloc[train_index].to_numpy(), y.iloc[train_index])
        fit_seconds = time.perf_counter() - started
        probabilities = pipeline.predict_proba(X.iloc[test_index].to_numpy())[:, 1]
        y_test = y.iloc[test_index]
        folds.append(
            {
                "auc": roc_auc_score(y_test, probabilities),
                "pr_auc": average_precision_score(y_test, probabilities),
                "f1": f1_score(y_test, (probabilities >= 0.5).astype(int)),
                "brier": brier_score_loss(y_test, probabilities),
                "fit_seconds": fit_seconds,
            }
        )
        last_pipeline, last_test = pipeline, X.iloc[test_index].to_numpy()

    latency = _single_row_latency_ms(last_pipeline, last_test)
    aucs = [fold["auc"] for fold in folds]
    result = {
        "auc_roc_mean": float(np.mean(aucs)),
        "auc_roc_std": float(np.std(aucs)),
        "pr_auc_mean": float(np.mean([fold["pr_auc"] for fold in folds])),
        "f1_mean": float(np.mean([fold["f1"] for fold in folds])),
        "brier_mean": float(np.mean([fold["brier"] for fold in folds])),
        "fit_seconds_mean": float(np.mean([fold["fit_seconds"] for fold in folds])),
        "single_row_predict_ms_median": latency,
        "explainer": spec["explainer"],
        "monotone": spec["monotone"],
        "per_fold_auc": [float(value) for value in aucs],
    }
    print(
        f"  {name:<26} AUC {result['auc_roc_mean']:.4f} +/- {result['auc_roc_std']:.4f}"
        f" | PR-AUC {result['pr_auc_mean']:.4f} | F1 {result['f1_mean']:.4f}"
        f" | Brier {result['brier_mean']:.4f} | predict {latency:.2f} ms"
    )
    return result


def _fresh(model):
    """An unfitted copy, so no fold ever sees another fold's fit."""
    from sklearn.base import clone

    return clone(model)


def _single_row_latency_ms(pipeline, rows: np.ndarray) -> float:
    """Median time to score one applicant, the way the API does (serial)."""
    model = pipeline.named_steps["model"]
    # Same tuning the API applies (MLScoringService._tune_for_single_row_inference).
    for estimator in [model, *getattr(model, "estimators_", [])]:
        if hasattr(estimator, "n_jobs"):
            estimator.n_jobs = 1
    scaler = pipeline.named_steps["scaler"]
    timings = []
    for index in range(LATENCY_RUNS):
        row = scaler.transform(rows[index % len(rows)].reshape(1, -1))
        started = time.perf_counter()
        model.predict_proba(row)
        timings.append((time.perf_counter() - started) * 1000.0)
    return float(np.median(timings))


def main() -> int:
    """Run the comparison and write ``model_comparison.json``."""
    raw = load_datasets(("credit_risk",))
    mapped = {"credit_risk": map_credit_risk(raw["credit_risk"])}
    winner = next(c for c in build_candidates(mapped) if c.name == "credit_risk_shared")
    X, y = winner.frame[winner.features], winner.frame[TARGET]
    print(f"\ncredit_risk_shared: {len(X):,} rows, features {winner.features}")
    print(f"{N_SPLITS}-fold stratified CV, scaler + SMOTE inside each training fold\n")

    results = {
        name: evaluate(name, spec, X, y) for name, spec in candidates(winner.features).items()
    }
    payload = {
        "dataset": "credit_risk_shared",
        "rows": int(len(X)),
        "features": winner.features,
        "protocol": (
            f"StratifiedKFold({N_SPLITS}, shuffle=True, random_state={RANDOM_STATE}); "
            "StandardScaler + SMOTE fitted inside each training fold; "
            "production monotone constraints on the tree models"
        ),
        "models": results,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {OUTPUT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
