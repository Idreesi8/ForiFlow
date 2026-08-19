"""AUC ladder experiments for ForiFlow.

Run from ``backend``::

    python -m ml.auc_ladder --step baseline
    python -m ml.auc_ladder --step class_weight
    python -m ml.auc_ladder --step shap_rank
    python -m ml.auc_ladder --step optuna
    python -m ml.auc_ladder --step blend
    python -m ml.auc_ladder --step final

Every metric written to ``ml/auc_ladder.json`` is computed by this process.
Nothing is invented. Optuna stays on-disk (no cloud).
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, train_test_split

from ml.features import ML_DIR
from ml.shap_utils import positive_class_shap
from ml.train_real_model import (
    ENSEMBLE_WEIGHTS,
    N_SPLITS,
    RANDOM_STATE,
    SHAP_BACKGROUND_ROWS,
    TARGET,
    build_candidates,
    build_pipeline,
    build_shap_explainers,
    cross_validate,
    load_datasets,
    map_credit_risk,
    map_loan_default,
)

LADDER_PATH = ML_DIR / "auc_ladder.json"


def load_winner() -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """Load the served training set: credit_risk_shared, three features."""
    raw = load_datasets()
    mapped = {
        "credit_risk": map_credit_risk(raw["credit_risk"]),
        "loan_default": map_loan_default(raw["loan_default"]),
    }
    winner = next(c for c in build_candidates(mapped) if c.name == "credit_risk_shared")
    X = winner.frame[winner.features]
    y = winner.frame[TARGET].astype(int)
    return X, y, winner.features


def read_ladder() -> dict:
    if LADDER_PATH.exists():
        return json.loads(LADDER_PATH.read_text(encoding="utf-8"))
    return {"steps": []}


def write_step(name: str, payload: dict) -> None:
    ladder = read_ladder()
    ladder["steps"] = [s for s in ladder.get("steps", []) if s.get("name") != name]
    payload = {"name": name, **payload, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    ladder["steps"].append(payload)
    LADDER_PATH.write_text(json.dumps(ladder, indent=2), encoding="utf-8")
    print(f"\nWrote {LADDER_PATH} step={name}")


def report_class_balance(y: pd.Series, label: str) -> dict:
    n = int(len(y))
    n_pos = int(y.sum())
    n_neg = n - n_pos
    ratio = {
        "label": label,
        "n": n,
        "n_neg": n_neg,
        "n_pos": n_pos,
        "pos_rate": float(y.mean()),
        "neg_to_pos": float(n_neg / n_pos) if n_pos else None,
    }
    print(
        f"{label}: n={n:,}  non-default={n_neg:,}  default={n_pos:,}  "
        f"pos_rate={ratio['pos_rate']*100:.2f}%  neg/pos={ratio['neg_to_pos']:.3f}"
    )
    return ratio


def step_baseline() -> None:
    """Current production recipe: SMOTE inside 5-fold CV."""
    X, y, features = load_winner()
    balance = report_class_balance(y, "credit_risk_shared (raw)")
    mean_auc, std_auc, mean_f1, folds = cross_validate(X, y, "baseline SMOTE")
    write_step(
        "baseline",
        {
            "features": features,
            "class_balance": balance,
            "imbalance": "SMOTE inside each CV fold, 50/50 after resample",
            "ensemble": {"type": "VotingClassifier soft", "weights": list(ENSEMBLE_WEIGHTS)},
            "auc_roc_mean": mean_auc,
            "auc_roc_std": std_auc,
            "f1_mean": mean_f1,
            "per_fold": folds,
        },
    )


def step_features() -> None:
    """Record that the requested SME time-series features are not derivable.

    No mapper change: inventing columns would violate the serving contract
    (intake form cannot supply monthly revenue histories or DPD counts).
    AUC is therefore unchanged from baseline — this is not a skipped measurement,
    it is a schema constraint.
    """
    ladder = read_ladder()
    baseline = next(s for s in ladder["steps"] if s["name"] == "baseline")
    requested = {
        "debt_to_income": (
            "Not on the winning dataset. credit_risk_dataset.csv has no existing-debt "
            "column. Loan_default.csv has DTIRatio but that candidate's CV AUC is 0.62 "
            "and is not served."
        ),
        "cash_flow_volatility": (
            "Not derivable. Neither CSV is a panel: one income snapshot per row, "
            "no rolling revenue series."
        ),
        "revenue_trend_slope": (
            "Not derivable. No date index and no repeated revenue observations."
        ),
        "payment_delay_frequency": (
            "Not derivable. credit_risk has only cb_person_default_on_file (Y/N); "
            "Loan_default has a 300-850 CreditScore. No DPD or late-count."
        ),
    }
    print("Requested features vs schema:")
    for name, reason in requested.items():
        print(f"  SKIP {name}: {reason}")
    write_step(
        "features",
        {
            "added": [],
            "skipped": requested,
            "auc_roc_mean": baseline["auc_roc_mean"],
            "auc_roc_std": baseline["auc_roc_std"],
            "f1_mean": baseline["f1_mean"],
            "note": "No columns added. AUC copied from baseline because the model is unchanged.",
            "improved": False,
        },
    )


def step_class_weight() -> None:
    """Replace SMOTE with scale_pos_weight + class_weight='balanced'."""
    X, y, features = load_winner()
    raw = report_class_balance(y, "before (natural distribution used in every train fold)")
    spw = float(raw["neg_to_pos"])
    print(
        f"XGBoost scale_pos_weight={spw:.4f} (neg/pos). "
        "RandomForest class_weight='balanced'. No SMOTE; train-fold class ratio stays natural."
    )
    mean_auc, std_auc, mean_f1, folds = cross_validate(
        X, y, "class_weight (no SMOTE)", imbalance="class_weight"
    )
    baseline = next(s for s in read_ladder()["steps"] if s["name"] == "baseline")
    write_step(
        "class_weight",
        {
            "features": features,
            "class_balance_before": raw,
            "class_balance_after_training": {
                "note": "No resampling. Each train fold keeps the natural ~21.82% default rate.",
                "scale_pos_weight": spw,
                "rf_class_weight": "balanced",
                "pos_rate": raw["pos_rate"],
            },
            "auc_roc_mean": mean_auc,
            "auc_roc_std": std_auc,
            "f1_mean": mean_f1,
            "per_fold": folds,
            "improved": mean_auc > baseline["auc_roc_mean"],
            "delta_vs_baseline": mean_auc - baseline["auc_roc_mean"],
        },
    )


def _class_weight_pipeline(features: list[str], y_train: pd.Series):
    return build_pipeline(features, y_train=y_train, imbalance="class_weight")


def step_shap_rank() -> None:
    """Rank features by mean |SHAP|, then ablate the lowest without guessing."""
    X, y, features = load_winner()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE
    )
    pipe = _class_weight_pipeline(features, y_train)
    pipe.fit(X_train, y_train)
    model = pipe.named_steps["model"]
    scaler = pipe.named_steps["scaler"]
    shap_rows = min(1000, len(X_test))
    X_shap, _, _, _ = train_test_split(
        X_test, y_test, train_size=shap_rows, stratify=y_test, random_state=RANDOM_STATE
    )
    X_train_s = scaler.transform(X_train.to_numpy())
    X_shap_s = scaler.transform(X_shap.to_numpy())
    rng = np.random.default_rng(RANDOM_STATE)
    bg_idx = rng.choice(len(X_train_s), size=min(SHAP_BACKGROUND_ROWS, len(X_train_s)), replace=False)
    bundle = build_shap_explainers(model, X_train_s[bg_idx], features)

    mean_abs = np.zeros(len(features))
    weights = bundle["weights"]
    print(f"Ranking on {shap_rows} stratified hold-out rows (TreeExplainer, probability space).")
    for name, explainer in bundle["explainers"].items():
        contrib = np.abs(positive_class_shap(explainer.shap_values(X_shap_s))).mean(axis=0)
        mean_abs += weights[name] * contrib
        print(f"  {name} mean|SHAP|: {dict(zip(features, np.round(contrib, 6)))}")

    ranking = sorted(
        (
            {"feature": feat, "mean_abs_shap": float(value)}
            for feat, value in zip(features, mean_abs, strict=True)
        ),
        key=lambda row: row["mean_abs_shap"],
        reverse=True,
    )
    print("\nWeighted ensemble mean |SHAP| (hold-out, class-weight model):")
    for i, row in enumerate(ranking, start=1):
        print(f"  {i}. {row['feature']:<24} {row['mean_abs_shap']:.6f}")

    lowest = ranking[-1]["feature"]
    print(f"\nLowest-ranked candidate to drop: {lowest}")
    print("Running ablation CV with that feature removed (not yet a production change).")
    kept = [f for f in features if f != lowest]
    mean_auc, std_auc, mean_f1, folds = cross_validate(
        X[kept], y, f"ablate {lowest}", imbalance="class_weight"
    )
    class_weight = next(s for s in read_ladder()["steps"] if s["name"] == "class_weight")
    drop = mean_auc > class_weight["auc_roc_mean"]
    print(
        f"Ablation AUC {mean_auc:.4f} vs class_weight {class_weight['auc_roc_mean']:.4f} "
        f"-> {'DROP' if drop else 'KEEP all features'}"
    )
    write_step(
        "shap_rank",
        {
            "ranking": ranking,
            "shap_holdout_rows": shap_rows,
            "proposed_drop": lowest,
            "dropped": [lowest] if drop else [],
            "features_kept": kept if drop else features,
            "ablation_auc_roc_mean": mean_auc,
            "ablation_auc_roc_std": std_auc,
            "ablation_f1_mean": mean_f1,
            "ablation_per_fold": folds,
            "auc_roc_mean": mean_auc if drop else class_weight["auc_roc_mean"],
            "auc_roc_std": std_auc if drop else class_weight["auc_roc_std"],
            "improved": drop and mean_auc > class_weight["auc_roc_mean"],
            "note": (
                f"Dropped {lowest}" if drop else f"Kept all three features; dropping {lowest} did not help."
            ),
        },
    )


def step_optuna() -> None:
    """Tune XGB + RF with Optuna, maximizing stratified 5-fold AUC-ROC."""
    try:
        import optuna
    except ImportError as error:
        raise SystemExit("Install optuna locally: pip install optuna") from error

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    X, y, features = load_winner()
    shap_step = next(s for s in read_ladder()["steps"] if s["name"] == "shap_rank")
    used_features = shap_step["features_kept"]
    X = X[used_features]

    def objective(trial: optuna.Trial) -> float:
        xgb_overrides = {
            "max_depth": trial.suggest_int("xgb_max_depth", 3, 8),
            "learning_rate": trial.suggest_float("xgb_learning_rate", 0.02, 0.2, log=True),
            "min_child_weight": trial.suggest_int("xgb_min_child_weight", 1, 20),
            "subsample": trial.suggest_float("xgb_subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("xgb_colsample_bytree", 0.6, 1.0),
        }
        rf_overrides = {
            "n_estimators": trial.suggest_int("rf_n_estimators", 100, 400, step=50),
            "max_depth": trial.suggest_int("rf_max_depth", 6, 20),
            "min_samples_leaf": trial.suggest_int("rf_min_samples_leaf", 10, 80),
        }
        mean_auc, std_auc, _, _ = cross_validate(
            X,
            y,
            f"optuna trial {trial.number}",
            imbalance="class_weight",
            xgb_overrides=xgb_overrides,
            rf_overrides=rf_overrides,
        )
        trial.set_user_attr("auc_std", std_auc)
        return mean_auc

    def log_trial(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        if trial.value is None:
            print(f"trial={trial.number} FAILED")
            return
        marker = " NEW BEST" if study.best_trial.number == trial.number else ""
        print(
            f"trial={trial.number} AUC={trial.value:.4f} "
            f"std={float(trial.user_attrs.get('auc_std', float('nan'))):.4f} "
            f"best_so_far={study.best_value:.4f}{marker} params={trial.params}"
        )

    storage = f"sqlite:///{(ML_DIR / 'optuna_auc.db').as_posix()}"
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=RANDOM_STATE),
        storage=storage,
        study_name="foriflow_auc",
        load_if_exists=True,
    )
    remaining = max(0, 20 - len([t for t in study.trials if t.value is not None]))
    if remaining == 0:
        print(f"Study already has {len(study.trials)} trials; not adding more.")
    else:
        print(f"Running {remaining} Optuna trials (stratified 5-fold AUC). Local SQLite only.")
        study.optimize(objective, n_trials=remaining, callbacks=[log_trial], show_progress_bar=False)
    best = study.best_trial
    all_trials = []
    running_best = -1.0
    best_so_far = []
    for trial in study.trials:
        if trial.value is None:
            continue
        all_trials.append(
            {
                "trial": trial.number,
                "auc_roc_mean": float(trial.value),
                "auc_roc_std": float(trial.user_attrs.get("auc_std", float("nan"))),
                "params": trial.params,
            }
        )
        if trial.value > running_best:
            running_best = float(trial.value)
            best_so_far.append(all_trials[-1])
    write_step(
        "optuna",
        {
            "features": used_features,
            "n_trials": len(all_trials),
            "best_trial": best.number,
            "best_params": best.params,
            "trials": all_trials,
            "best_so_far": best_so_far,
            "auc_roc_mean": float(best.value),
            "auc_roc_std": float(best.user_attrs.get("auc_std", float("nan"))),
            "improved": float(best.value)
            > next(s for s in read_ladder()["steps"] if s["name"] == "shap_rank")["auc_roc_mean"],
        },
    )


def _oof_member_probs(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    xgb_overrides: dict | None,
    rf_overrides: dict | None,
    weights: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    splitter = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    p_xgb = np.zeros(len(X))
    p_rf = np.zeros(len(X))
    for train_index, test_index in splitter.split(X, y):
        y_train = y.iloc[train_index]
        pipe = build_pipeline(
            list(X.columns),
            y_train=y_train,
            imbalance="class_weight",
            xgb_overrides=xgb_overrides,
            rf_overrides=rf_overrides,
            weights=weights,
        )
        pipe.fit(X.iloc[train_index], y_train)
        model = pipe.named_steps["model"]
        scaled = pipe.named_steps["scaler"].transform(X.iloc[test_index].to_numpy())
        p_xgb[test_index] = model.named_estimators_["xgb"].predict_proba(scaled)[:, 1]
        p_rf[test_index] = model.named_estimators_["rf"].predict_proba(scaled)[:, 1]
    return p_xgb, p_rf, y.to_numpy()


def step_blend() -> None:
    """Fit a blend weight on OOF member probabilities; compare to logistic stack."""
    X, y, features = load_winner()
    shap_step = next(s for s in read_ladder()["steps"] if s["name"] == "shap_rank")
    optuna_step = next(s for s in read_ladder()["steps"] if s["name"] == "optuna")
    used = shap_step["features_kept"]
    X = X[used]
    params = optuna_step["best_params"]
    xgb_overrides = {
        "max_depth": params["xgb_max_depth"],
        "learning_rate": params["xgb_learning_rate"],
        "min_child_weight": params["xgb_min_child_weight"],
        "subsample": params["xgb_subsample"],
        "colsample_bytree": params["xgb_colsample_bytree"],
    }
    rf_overrides = {
        "n_estimators": params["rf_n_estimators"],
        "max_depth": params["rf_max_depth"],
        "min_samples_leaf": params["rf_min_samples_leaf"],
    }
    print("Collecting out-of-fold member probabilities...")
    p_xgb, p_rf, y_np = _oof_member_probs(
        X, y, xgb_overrides=xgb_overrides, rf_overrides=rf_overrides, weights=ENSEMBLE_WEIGHTS
    )
    grid = []
    best_w, best_auc = 0.6, -1.0
    for w in np.linspace(0.0, 1.0, 21):
        auc = float(roc_auc_score(y_np, w * p_xgb + (1.0 - w) * p_rf))
        grid.append({"xgb_weight": float(w), "rf_weight": float(1.0 - w), "auc": auc})
        if auc > best_auc:
            best_w, best_auc = float(w), auc
    print(f"Best OOF blend: xgb={best_w:.2f} rf={1-best_w:.2f} AUC={best_auc:.4f}")

    meta = LogisticRegression(max_iter=1000, solver="lbfgs")
    meta.fit(np.column_stack([p_xgb, p_rf]), y_np)
    stack_auc = float(roc_auc_score(y_np, meta.predict_proba(np.column_stack([p_xgb, p_rf]))[:, 1]))
    print(f"Logistic stack (fit on same OOF, optimistic) AUC={stack_auc:.4f}")

    # Per-fold AUC of the chosen blend, for variance (weight was global).
    splitter = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    fold_aucs = []
    for _, test_index in splitter.split(X, y):
        blended = best_w * p_xgb[test_index] + (1.0 - best_w) * p_rf[test_index]
        fold_aucs.append(float(roc_auc_score(y_np[test_index], blended)))
    write_step(
        "blend",
        {
            "features": used,
            "optimal_xgb_weight": best_w,
            "optimal_rf_weight": 1.0 - best_w,
            "grid": grid,
            "logistic_stack_auc_optimistic": stack_auc,
            "auc_roc_mean": float(np.mean(fold_aucs)),
            "auc_roc_std": float(np.std(fold_aucs)),
            "oof_auc_global_weight": best_auc,
            "per_fold": [{"auc": a} for a in fold_aucs],
            "improved": float(np.mean(fold_aucs)) > optuna_step["auc_roc_mean"],
        },
    )


def step_final() -> None:
    """Stratified 5-fold CV of the stacked recipe chosen by earlier steps."""
    X, y, features = load_winner()
    shap_step = next(s for s in read_ladder()["steps"] if s["name"] == "shap_rank")
    optuna_step = next(s for s in read_ladder()["steps"] if s["name"] == "optuna")
    blend_step = next(s for s in read_ladder()["steps"] if s["name"] == "blend")
    used = shap_step["features_kept"]
    X = X[used]
    params = optuna_step["best_params"]
    xgb_overrides = {
        "max_depth": params["xgb_max_depth"],
        "learning_rate": params["xgb_learning_rate"],
        "min_child_weight": params["xgb_min_child_weight"],
        "subsample": params["xgb_subsample"],
        "colsample_bytree": params["xgb_colsample_bytree"],
    }
    rf_overrides = {
        "n_estimators": params["rf_n_estimators"],
        "max_depth": params["rf_max_depth"],
        "min_samples_leaf": params["rf_min_samples_leaf"],
    }
    weights = (blend_step["optimal_xgb_weight"], blend_step["optimal_rf_weight"])
    mean_auc, std_auc, mean_f1, folds = cross_validate(
        X,
        y,
        "final (class_weight + tuned params + OOF blend weights)",
        imbalance="class_weight",
        xgb_overrides=xgb_overrides,
        rf_overrides=rf_overrides,
        weights=weights,
    )
    baseline = next(s for s in read_ladder()["steps"] if s["name"] == "baseline")
    write_step(
        "final",
        {
            "features": used,
            "imbalance": "class_weight",
            "xgb_overrides": xgb_overrides,
            "rf_overrides": rf_overrides,
            "weights": list(weights),
            "auc_roc_mean": mean_auc,
            "auc_roc_std": std_auc,
            "f1_mean": mean_f1,
            "per_fold": folds,
            "delta_vs_baseline": mean_auc - baseline["auc_roc_mean"],
            "unstable": std_auc > 0.02,
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--step",
        required=True,
        choices=("baseline", "features", "class_weight", "shap_rank", "optuna", "blend", "final"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dispatch = {
        "baseline": step_baseline,
        "features": step_features,
        "class_weight": step_class_weight,
        "shap_rank": step_shap_rank,
        "optuna": step_optuna,
        "blend": step_blend,
        "final": step_final,
    }
    dispatch[args.step]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
