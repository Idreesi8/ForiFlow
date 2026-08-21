"""Give Me Some Credit AUC ladder — experiment only.

Does not write foriflow_model.pkl, scaler.pkl, shap_explainer.pkl, or
feature_names.json. Results go to ``ml/gmsc_auc_ladder.json``.

Run from ``backend``::

    python -m ml.auc_ladder_gmsc --step baseline
    python -m ml.auc_ladder_gmsc --step features
"""

from __future__ import annotations

import argparse
import json
import time
import warnings

import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline as SkPipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from ml.features import DATA_DIR, ML_DIR
from ml.shap_utils import positive_class_shap
from ml.train_real_model import (
    ENSEMBLE_WEIGHTS,
    N_SPLITS,
    RANDOM_STATE,
    SHAP_BACKGROUND_ROWS,
    build_shap_explainers,
    scale_pos_weight_from,
)

warnings.filterwarnings("ignore", category=UserWarning)

LADDER_PATH = ML_DIR / "gmsc_auc_ladder.json"
DATA_PATH = DATA_DIR / "cs-training.csv"
TARGET = "SeriousDlqin2yrs"

BASE_FEATURES = [
    "RevolvingUtilizationOfUnsecuredLines",
    "age",
    "NumberOfTime30-59DaysPastDueNotWorse",
    "DebtRatio",
    "MonthlyIncome",
    "NumberOfOpenCreditLinesAndLoans",
    "NumberOfTimes90DaysLate",
    "NumberRealEstateLoansOrLines",
    "NumberOfTime60-89DaysPastDueNotWorse",
    "NumberOfDependents",
]
IMPUTE_COLS = ["MonthlyIncome", "NumberOfDependents"]
DPD_COLS = [
    "NumberOfTime30-59DaysPastDueNotWorse",
    "NumberOfTime60-89DaysPastDueNotWorse",
    "NumberOfTimes90DaysLate",
]
SENTINELS = {96, 98}

KEPT_FLAGS = {
    "income_missing_flag": True,
    "recode_dpd_sentinel": False,
    "winsorize_util": True,
}

# Same directionality idea as production XGB, mapped onto GMSC columns.
# Unused names default to 0 in build_ensemble.
MONOTONE = {
    "RevolvingUtilizationOfUnsecuredLines": 1,
    "age": -1,
    "NumberOfTime30-59DaysPastDueNotWorse": 1,
    "DebtRatio": 1,
    "MonthlyIncome": -1,
    "NumberOfOpenCreditLinesAndLoans": 0,
    "NumberOfTimes90DaysLate": 1,
    "NumberRealEstateLoansOrLines": 0,
    "NumberOfTime60-89DaysPastDueNotWorse": 1,
    "NumberOfDependents": 0,
    "income_missing": 0,
    "dpd_sentinel": 1,
}


def load_gmsc() -> tuple[pd.DataFrame, pd.Series]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Expected {DATA_PATH}")
    raw = pd.read_csv(DATA_PATH)
    y = raw[TARGET].astype(int)
    X = raw.drop(columns=[TARGET, "Unnamed: 0"], errors="ignore")
    missing = [name for name in BASE_FEATURES if name not in X.columns]
    extra = [name for name in X.columns if name not in BASE_FEATURES]
    if missing or extra:
        raise ValueError(f"Unexpected GMSC schema missing={missing} extra={extra}")
    return X[BASE_FEATURES].copy(), y


def read_ladder() -> dict:
    if LADDER_PATH.exists():
        return json.loads(LADDER_PATH.read_text(encoding="utf-8"))
    return {"dataset": "Give Me Some Credit (cs-training.csv)", "domain": "consumer_not_sme", "steps": []}


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
        f"{label}: n={n:,}  non-event={n_neg:,}  SeriousDlqin2yrs={n_pos:,}  "
        f"pos_rate={ratio['pos_rate']*100:.3f}%  neg/pos={ratio['neg_to_pos']:.3f}"
    )
    return ratio


def build_ensemble(
    features: list[str],
    *,
    scale_pos_weight: float = 1.0,
    rf_class_weight: str | dict | None = None,
    xgb_overrides: dict | None = None,
    rf_overrides: dict | None = None,
    weights: tuple[float, float] = ENSEMBLE_WEIGHTS,
) -> VotingClassifier:
    """Production-like XGB+RF soft vote; n_jobs=2 to keep Windows stable."""
    constraints = tuple(MONOTONE.get(name, 0) for name in features)
    xgb_params = {
        "monotone_constraints": constraints,
        "n_estimators": 300,
        "max_depth": 5,
        "learning_rate": 0.08,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "reg_lambda": 1.0,
        "min_child_weight": 5,
        "scale_pos_weight": scale_pos_weight,
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "tree_method": "hist",
        "enable_categorical": False,
        "random_state": RANDOM_STATE,
        "n_jobs": 2,
    }
    if xgb_overrides:
        xgb_params.update(xgb_overrides)
    rf_params = {
        "n_estimators": 250,
        "max_depth": 12,
        "min_samples_leaf": 40,
        "max_features": "sqrt",
        "class_weight": rf_class_weight,
        "random_state": RANDOM_STATE,
        "n_jobs": 2,
    }
    if rf_overrides:
        rf_params.update(rf_overrides)
    return VotingClassifier(
        estimators=[("xgb", XGBClassifier(**xgb_params)), ("rf", RandomForestClassifier(**rf_params))],
        voting="soft",
        weights=list(weights),
    )


def build_pipeline(
    features: list[str],
    *,
    y_train: pd.Series | None = None,
    imbalance: str = "smote",
    xgb_overrides: dict | None = None,
    rf_overrides: dict | None = None,
    weights: tuple[float, float] = ENSEMBLE_WEIGHTS,
):
    if imbalance == "smote":
        return ImbPipeline(
            steps=[
                ("scaler", StandardScaler()),
                ("smote", SMOTE(random_state=RANDOM_STATE, k_neighbors=5)),
                (
                    "model",
                    build_ensemble(
                        features,
                        xgb_overrides=xgb_overrides,
                        rf_overrides=rf_overrides,
                        weights=weights,
                    ),
                ),
            ]
        )
    if imbalance != "class_weight":
        raise ValueError(f"Unknown imbalance mode: {imbalance}")
    if y_train is None:
        raise ValueError("class_weight mode needs y_train")
    return SkPipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "model",
                build_ensemble(
                    features,
                    scale_pos_weight=scale_pos_weight_from(y_train),
                    rf_class_weight="balanced",
                    xgb_overrides=xgb_overrides,
                    rf_overrides=rf_overrides,
                    weights=weights,
                ),
            ),
        ]
    )


def _sentinel_mask(frame: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=frame.index)
    for column in DPD_COLS:
        mask = mask | frame[column].isin(SENTINELS)
    return mask.astype(int)


def prepare_fold(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    *,
    income_missing_flag: bool,
    recode_dpd_sentinel: bool,
    winsorize_util: bool,
    drop_features: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Fold-wise transforms. Medians and the 99th percentile come from train only."""
    train = X_train.copy()
    test = X_test.copy()

    if income_missing_flag:
        train["income_missing"] = train["MonthlyIncome"].isna().astype(int)
        test["income_missing"] = test["MonthlyIncome"].isna().astype(int)

    if recode_dpd_sentinel:
        train["dpd_sentinel"] = _sentinel_mask(train)
        test["dpd_sentinel"] = _sentinel_mask(test)
        for column in DPD_COLS:
            train.loc[train[column].isin(SENTINELS), column] = np.nan
            test.loc[test[column].isin(SENTINELS), column] = np.nan

    impute_cols = list(IMPUTE_COLS)
    if recode_dpd_sentinel:
        impute_cols = impute_cols + DPD_COLS
    medians: dict[str, float] = {}
    for column in impute_cols:
        median = float(train[column].median())
        medians[column] = median
        train[column] = train[column].fillna(median)
        test[column] = test[column].fillna(median)

    util_p99 = None
    if winsorize_util:
        util_p99 = float(train["RevolvingUtilizationOfUnsecuredLines"].quantile(0.99))
        train["RevolvingUtilizationOfUnsecuredLines"] = train[
            "RevolvingUtilizationOfUnsecuredLines"
        ].clip(upper=util_p99)
        test["RevolvingUtilizationOfUnsecuredLines"] = test[
            "RevolvingUtilizationOfUnsecuredLines"
        ].clip(upper=util_p99)

    features = list(BASE_FEATURES)
    if income_missing_flag:
        features.append("income_missing")
    if recode_dpd_sentinel:
        features.append("dpd_sentinel")
    if drop_features:
        features = [name for name in features if name not in drop_features]
    return train[features], test[features], features


def cross_validate_gmsc(
    X: pd.DataFrame,
    y: pd.Series,
    label: str,
    *,
    income_missing_flag: bool = False,
    recode_dpd_sentinel: bool = False,
    winsorize_util: bool = False,
    imbalance: str = "smote",
    xgb_overrides: dict | None = None,
    rf_overrides: dict | None = None,
    weights: tuple[float, float] = ENSEMBLE_WEIGHTS,
    drop_features: list[str] | None = None,
    score_train: bool = False,
) -> tuple[float, float, float, list[dict], list[str]]:
    splitter = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    folds: list[dict] = []
    features_used: list[str] = []

    print(f"\n{label}: {N_SPLITS}-fold CV on {len(X):,} rows")
    header = f"  {'fold':<6}{'AUC-ROC':>10}{'F1':>10}{'PR-AUC':>10}{'seconds':>10}"
    if score_train:
        header += f"{'trainAUC':>10}"
    print(header)

    for index, (train_index, test_index) in enumerate(splitter.split(X, y), start=1):
        started = time.perf_counter()
        X_train, X_test, features_used = prepare_fold(
            X.iloc[train_index],
            X.iloc[test_index],
            income_missing_flag=income_missing_flag,
            recode_dpd_sentinel=recode_dpd_sentinel,
            winsorize_util=winsorize_util,
            drop_features=drop_features,
        )
        y_train = y.iloc[train_index]
        y_test = y.iloc[test_index]
        pipeline = build_pipeline(
            features_used,
            y_train=y_train,
            imbalance=imbalance,
            xgb_overrides=xgb_overrides,
            rf_overrides=rf_overrides,
            weights=weights,
        )
        pipeline.fit(X_train, y_train)
        probabilities = pipeline.predict_proba(X_test)[:, 1]
        predictions = (probabilities >= 0.5).astype(int)
        scores = {
            "auc": float(roc_auc_score(y_test, probabilities)),
            "f1": float(f1_score(y_test, predictions, zero_division=0)),
            "pr_auc": float(average_precision_score(y_test, probabilities)),
            "seconds": float(time.perf_counter() - started),
        }
        if score_train:
            train_prob = pipeline.predict_proba(X_train)[:, 1]
            scores["train_auc"] = float(roc_auc_score(y_train, train_prob))
        folds.append(scores)
        line = (
            f"  {index:<6}{scores['auc']:>10.4f}{scores['f1']:>10.4f}"
            f"{scores['pr_auc']:>10.4f}{scores['seconds']:>10.1f}"
        )
        if score_train:
            line += f"{scores['train_auc']:>10.4f}"
        print(line)

    auc_values = [fold["auc"] for fold in folds]
    mean_auc, std_auc = float(np.mean(auc_values)), float(np.std(auc_values))
    mean_f1 = float(np.mean([fold["f1"] for fold in folds]))
    print(f"  mean  {mean_auc:>10.4f}{mean_f1:>10.4f}")
    print(f"  AUC-ROC {mean_auc:.4f} +/- {std_auc:.4f} | F1 {mean_f1:.4f}")
    if score_train:
        train_mean = float(np.mean([fold["train_auc"] for fold in folds]))
        gap = train_mean - mean_auc
        print(f"  train AUC {train_mean:.4f} | train-test gap {gap:+.4f}")
    return mean_auc, std_auc, mean_f1, folds, features_used


def step_baseline() -> None:
    X, y = load_gmsc()
    balance = report_class_balance(y, "GMSC cs-training (raw labels)")
    mean_auc, std_auc, mean_f1, folds, features = cross_validate_gmsc(X, y, "GMSC baseline SMOTE")
    write_step(
        "baseline",
        {
            "features": features,
            "imputation": "fold-wise median on MonthlyIncome and NumberOfDependents",
            "dpd_96_98": "raw counts, not recoded",
            "income_missing_flag": False,
            "winsorize_util": False,
            "imbalance": "SMOTE inside each CV fold (production architecture)",
            "ensemble": {"type": "VotingClassifier soft", "weights": list(ENSEMBLE_WEIGHTS)},
            "class_balance": balance,
            "auc_roc_mean": mean_auc,
            "auc_roc_std": std_auc,
            "f1_mean": mean_f1,
            "per_fold": folds,
        },
    )


def step_features() -> None:
    X, y = load_gmsc()
    baseline = next(s for s in read_ladder()["steps"] if s["name"] == "baseline")
    base_auc = baseline["auc_roc_mean"]
    trials = [
        {
            "key": "a_income_missing",
            "label": "(a) income_missing flag",
            "income_missing_flag": True,
            "recode_dpd_sentinel": False,
            "winsorize_util": False,
        },
        {
            "key": "b_dpd_sentinel",
            "label": "(b) DPD 96/98 -> dpd_sentinel + NaN/median in counts",
            "income_missing_flag": False,
            "recode_dpd_sentinel": True,
            "winsorize_util": False,
        },
        {
            "key": "c_winsorize_util",
            "label": "(c) RevolvingUtilization winsorized at train-fold 99th",
            "income_missing_flag": False,
            "recode_dpd_sentinel": False,
            "winsorize_util": True,
        },
    ]
    results = []
    kept = []
    for trial in trials:
        mean_auc, std_auc, mean_f1, folds, features = cross_validate_gmsc(
            X,
            y,
            trial["label"],
            income_missing_flag=trial["income_missing_flag"],
            recode_dpd_sentinel=trial["recode_dpd_sentinel"],
            winsorize_util=trial["winsorize_util"],
        )
        keep = mean_auc >= base_auc
        row = {
            "key": trial["key"],
            "label": trial["label"],
            "features": features,
            "auc_roc_mean": mean_auc,
            "auc_roc_std": std_auc,
            "f1_mean": mean_f1,
            "delta_vs_baseline": mean_auc - base_auc,
            "keep": keep,
            "per_fold": folds,
        }
        results.append(row)
        verdict = "KEEP" if keep else "DROP"
        print(
            f"  -> {verdict} {trial['key']}: AUC {mean_auc:.4f} vs baseline {base_auc:.4f} "
            f"(delta {mean_auc - base_auc:+.4f})"
        )
        if keep:
            kept.append(trial)
        write_step(
            "features",
            {
                "baseline_auc_roc_mean": base_auc,
                "trials": results,
                "kept_keys": [t["key"] for t in kept],
                "combined": None,
                "auc_roc_mean": max((r["auc_roc_mean"] for r in results if r["keep"]), default=base_auc),
                "auc_roc_std": next(
                    (r["auc_roc_std"] for r in sorted(results, key=lambda row: row["auc_roc_mean"], reverse=True) if r["keep"]),
                    baseline["auc_roc_std"],
                ),
                "improved": any(r["keep"] and r["auc_roc_mean"] > base_auc for r in results),
                "note": "Checkpoint after each individual trial; combined run follows if 2+ kept.",
            },
        )

    combined = None
    if kept:
        flags = {
            "income_missing_flag": any(t["income_missing_flag"] for t in kept),
            "recode_dpd_sentinel": any(t["recode_dpd_sentinel"] for t in kept),
            "winsorize_util": any(t["winsorize_util"] for t in kept),
        }
        if sum(flags.values()) >= 2:
            mean_auc, std_auc, mean_f1, folds, features = cross_validate_gmsc(
                X, y, "kept features combined", **flags
            )
            combined = {
                "features": features,
                "auc_roc_mean": mean_auc,
                "auc_roc_std": std_auc,
                "f1_mean": mean_f1,
                "delta_vs_baseline": mean_auc - base_auc,
                "per_fold": folds,
                "flags": flags,
            }
            print(f"  combined kept AUC {mean_auc:.4f} +/- {std_auc:.4f}")

    best_single = max(results, key=lambda row: row["auc_roc_mean"])
    if combined and combined["auc_roc_mean"] >= best_single["auc_roc_mean"]:
        step_auc, step_std = combined["auc_roc_mean"], combined["auc_roc_std"]
    elif kept:
        winner = max((r for r in results if r["keep"]), key=lambda row: row["auc_roc_mean"])
        step_auc, step_std = winner["auc_roc_mean"], winner["auc_roc_std"]
    else:
        step_auc, step_std = base_auc, baseline["auc_roc_std"]

    write_step(
        "features",
        {
            "baseline_auc_roc_mean": base_auc,
            "trials": results,
            "kept_keys": [t["key"] for t in kept],
            "combined": combined,
            "auc_roc_mean": step_auc,
            "auc_roc_std": step_std,
            "improved": step_auc > base_auc,
        },
    )


def step_combined() -> None:
    """Union of individually kept transforms: income_missing + util winsorize."""
    X, y = load_gmsc()
    baseline = next(s for s in read_ladder()["steps"] if s["name"] == "baseline")
    features_step = next(s for s in read_ladder()["steps"] if s["name"] == "features")
    base_auc = baseline["auc_roc_mean"]
    mean_auc, std_auc, mean_f1, folds, features = cross_validate_gmsc(
        X,
        y,
        "kept features combined (income_missing + util 99th winsorize)",
        income_missing_flag=True,
        recode_dpd_sentinel=False,
        winsorize_util=True,
    )
    combined = {
        "features": features,
        "auc_roc_mean": mean_auc,
        "auc_roc_std": std_auc,
        "f1_mean": mean_f1,
        "delta_vs_baseline": mean_auc - base_auc,
        "per_fold": folds,
        "flags": {
            "income_missing_flag": True,
            "recode_dpd_sentinel": False,
            "winsorize_util": True,
        },
    }
    best_single = max(features_step["trials"], key=lambda row: row["auc_roc_mean"])
    if mean_auc >= best_single["auc_roc_mean"]:
        step_auc, step_std = mean_auc, std_auc
    else:
        step_auc, step_std = best_single["auc_roc_mean"], best_single["auc_roc_std"]
    write_step(
        "features",
        {
            "baseline_auc_roc_mean": base_auc,
            "trials": features_step["trials"],
            "kept_keys": features_step["kept_keys"],
            "combined": combined,
            "auc_roc_mean": step_auc,
            "auc_roc_std": step_std,
            "improved": step_auc > base_auc,
        },
    )


def _prev(name: str) -> dict:
    return next(s for s in read_ladder()["steps"] if s["name"] == name)


def _optuna_overrides(params: dict) -> tuple[dict, dict]:
    xgb_overrides = {
        "max_depth": params["xgb_max_depth"],
        "learning_rate": params["xgb_learning_rate"],
        "min_child_weight": params["xgb_min_child_weight"],
        "subsample": params["xgb_subsample"],
        "colsample_bytree": params["xgb_colsample_bytree"],
        "n_jobs": 2,
    }
    rf_overrides = {
        "n_estimators": params["rf_n_estimators"],
        "max_depth": params["rf_max_depth"],
        "min_samples_leaf": params["rf_min_samples_leaf"],
        "n_jobs": 2,
    }
    return xgb_overrides, rf_overrides


def step_class_weight() -> None:
    """Replace SMOTE with scale_pos_weight + class_weight='balanced' on kept features."""
    X, y = load_gmsc()
    raw = report_class_balance(y, "before (natural distribution used in every train fold)")
    spw = float(raw["neg_to_pos"])
    print(
        f"XGBoost scale_pos_weight={spw:.4f} (neg/pos). "
        "RandomForest class_weight='balanced'. No SMOTE; train-fold class ratio stays natural."
    )
    mean_auc, std_auc, mean_f1, folds, features = cross_validate_gmsc(
        X,
        y,
        "GMSC class_weight on kept features",
        imbalance="class_weight",
        **KEPT_FLAGS,
    )
    features_step = _prev("features")
    write_step(
        "class_weight",
        {
            "features": features,
            "class_balance_before": raw,
            "class_balance_after_training": {
                "note": "No resampling. Each train fold keeps the natural ~6.684% event rate.",
                "scale_pos_weight": spw,
                "rf_class_weight": "balanced",
                "pos_rate": raw["pos_rate"],
            },
            "auc_roc_mean": mean_auc,
            "auc_roc_std": std_auc,
            "f1_mean": mean_f1,
            "per_fold": folds,
            "improved": mean_auc > features_step["auc_roc_mean"],
            "delta_vs_kept_features": mean_auc - features_step["auc_roc_mean"],
        },
    )


def step_shap_rank() -> None:
    X, y = load_gmsc()
    X_train_raw, X_test_raw, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE
    )
    X_train, X_test, features = prepare_fold(X_train_raw, X_test_raw, **KEPT_FLAGS)
    pipe = build_pipeline(features, y_train=y_train, imbalance="class_weight")
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
        print(f"  {i}. {row['feature']:<40} {row['mean_abs_shap']:.6f}")

    lowest = ranking[-1]["feature"]
    print(f"\nLowest-ranked candidate to drop: {lowest}")
    mean_auc, std_auc, mean_f1, folds, kept_after = cross_validate_gmsc(
        X,
        y,
        f"ablate {lowest}",
        imbalance="class_weight",
        drop_features=[lowest],
        **KEPT_FLAGS,
    )
    class_weight = _prev("class_weight")
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
            "features_kept": kept_after if drop else features,
            "ablation_auc_roc_mean": mean_auc,
            "ablation_auc_roc_std": std_auc,
            "ablation_f1_mean": mean_f1,
            "ablation_per_fold": folds,
            "auc_roc_mean": mean_auc if drop else class_weight["auc_roc_mean"],
            "auc_roc_std": std_auc if drop else class_weight["auc_roc_std"],
            "improved": drop,
            "note": f"Dropped {lowest}" if drop else f"Kept all features; dropping {lowest} did not help.",
        },
    )


def step_optuna() -> None:
    try:
        import optuna
    except ImportError as error:
        raise SystemExit("Install optuna locally: pip install optuna") from error

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    X, y = load_gmsc()
    shap_step = _prev("shap_rank")
    dropped = shap_step["dropped"]

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
            "n_jobs": 1,
        }
        mean_auc, std_auc, _, _, _ = cross_validate_gmsc(
            X,
            y,
            f"optuna trial {trial.number}",
            imbalance="class_weight",
            xgb_overrides=xgb_overrides,
            rf_overrides=rf_overrides,
            drop_features=dropped,
            **KEPT_FLAGS,
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

    storage = f"sqlite:///{(ML_DIR / 'gmsc_optuna_auc.db').as_posix()}"
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=RANDOM_STATE),
        storage=storage,
        study_name="gmsc_auc",
        load_if_exists=True,
    )
    remaining = max(0, 20 - len([t for t in study.trials if t.value is not None]))
    if remaining == 0:
        print(f"Study already has {len(study.trials)} complete trials; not adding more.")
    else:
        print(f"Running {remaining} Optuna trials (stratified 5-fold AUC). Local SQLite only.")
        study.optimize(
            objective,
            n_trials=remaining,
            callbacks=[log_trial],
            show_progress_bar=False,
            catch=(Exception,),
        )
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
                "features": shap_step["features_kept"],
                "dropped": dropped,
                "n_trials": len(all_trials),
                "best_trial": best.number,
                "best_params": best.params,
                "trials": all_trials,
                "best_so_far": best_so_far,
                "auc_roc_mean": float(best.value),
                "auc_roc_std": float(best.user_attrs.get("auc_std", float("nan"))),
                "improved": float(best.value) > shap_step["auc_roc_mean"],
            },
        )
    write_step(
        "optuna",
        {
            "features": shap_step["features_kept"],
            "dropped": dropped,
            "n_trials": len(all_trials),
            "best_trial": best.number,
            "best_params": best.params,
            "trials": all_trials,
            "best_so_far": best_so_far,
            "auc_roc_mean": float(best.value),
            "auc_roc_std": float(best.user_attrs.get("auc_std", float("nan"))),
            "improved": float(best.value) > shap_step["auc_roc_mean"],
        },
    )


def _oof_member_probs(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    xgb_overrides: dict | None,
    rf_overrides: dict | None,
    drop_features: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    splitter = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    p_xgb = np.zeros(len(X))
    p_rf = np.zeros(len(X))
    for train_index, test_index in splitter.split(X, y):
        y_train = y.iloc[train_index]
        X_train, X_test, features = prepare_fold(
            X.iloc[train_index], X.iloc[test_index], drop_features=drop_features, **KEPT_FLAGS
        )
        pipe = build_pipeline(
            features,
            y_train=y_train,
            imbalance="class_weight",
            xgb_overrides=xgb_overrides,
            rf_overrides=rf_overrides,
        )
        pipe.fit(X_train, y_train)
        model = pipe.named_steps["model"]
        scaled = pipe.named_steps["scaler"].transform(X_test.to_numpy())
        p_xgb[test_index] = model.named_estimators_["xgb"].predict_proba(scaled)[:, 1]
        p_rf[test_index] = model.named_estimators_["rf"].predict_proba(scaled)[:, 1]
    return p_xgb, p_rf, y.to_numpy()


def step_blend() -> None:
    X, y = load_gmsc()
    optuna_step = _prev("optuna")
    shap_step = _prev("shap_rank")
    xgb_overrides, rf_overrides = _optuna_overrides(optuna_step["best_params"])
    print("Collecting out-of-fold member probabilities...")
    p_xgb, p_rf, y_np = _oof_member_probs(
        X,
        y,
        xgb_overrides=xgb_overrides,
        rf_overrides=rf_overrides,
        drop_features=shap_step["dropped"],
    )
    grid = []
    best_w, best_auc = 0.6, -1.0
    for weight in np.linspace(0.0, 1.0, 21):
        auc = float(roc_auc_score(y_np, weight * p_xgb + (1.0 - weight) * p_rf))
        grid.append({"xgb_weight": float(weight), "rf_weight": float(1.0 - weight), "auc": auc})
        if auc > best_auc:
            best_w, best_auc = float(weight), auc
    print(f"Best OOF blend: xgb={best_w:.2f} rf={1-best_w:.2f} AUC={best_auc:.4f}")

    meta = LogisticRegression(max_iter=1000, solver="lbfgs")
    stacked = np.column_stack([p_xgb, p_rf])
    meta.fit(stacked, y_np)
    stack_auc = float(roc_auc_score(y_np, meta.predict_proba(stacked)[:, 1]))
    print(f"Logistic stack (fit on same OOF, optimistic) AUC={stack_auc:.4f}")

    splitter = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    fold_aucs = []
    for _, test_index in splitter.split(X, y):
        blended = best_w * p_xgb[test_index] + (1.0 - best_w) * p_rf[test_index]
        fold_aucs.append(float(roc_auc_score(y_np[test_index], blended)))
    write_step(
        "blend",
        {
            "features": shap_step["features_kept"],
            "optimal_xgb_weight": best_w,
            "optimal_rf_weight": 1.0 - best_w,
            "grid": grid,
            "logistic_stack_auc_optimistic": stack_auc,
            "auc_roc_mean": float(np.mean(fold_aucs)),
            "auc_roc_std": float(np.std(fold_aucs)),
            "oof_auc_global_weight": best_auc,
            "per_fold": [{"auc": auc} for auc in fold_aucs],
            "improved": float(np.mean(fold_aucs)) > optuna_step["auc_roc_mean"],
        },
    )


def step_final() -> None:
    X, y = load_gmsc()
    shap_step = _prev("shap_rank")
    optuna_step = _prev("optuna")
    blend_step = _prev("blend")
    xgb_overrides, rf_overrides = _optuna_overrides(optuna_step["best_params"])
    weights = (blend_step["optimal_xgb_weight"], blend_step["optimal_rf_weight"])
    mean_auc, std_auc, mean_f1, folds, features = cross_validate_gmsc(
        X,
        y,
        "GMSC final (class_weight + tuned params + OOF blend weights)",
        imbalance="class_weight",
        xgb_overrides=xgb_overrides,
        rf_overrides=rf_overrides,
        weights=weights,
        drop_features=shap_step["dropped"],
        score_train=True,
        **KEPT_FLAGS,
    )
    train_mean = float(np.mean([fold["train_auc"] for fold in folds]))
    features_step = _prev("features")
    write_step(
        "final",
        {
            "features": features,
            "imbalance": "class_weight",
            "xgb_overrides": {k: v for k, v in xgb_overrides.items() if k != "n_jobs"},
            "rf_overrides": {k: v for k, v in rf_overrides.items() if k != "n_jobs"},
            "weights": list(weights),
            "auc_roc_mean": mean_auc,
            "auc_roc_std": std_auc,
            "f1_mean": mean_f1,
            "train_auc_mean": train_mean,
            "train_test_gap": train_mean - mean_auc,
            "per_fold": folds,
            "delta_vs_production_schema": mean_auc - 0.7775762198241348,
            "delta_vs_gmsc_kept_features": mean_auc - features_step["auc_roc_mean"],
            "unstable": std_auc > 0.02,
            "domain": "consumer_not_sme",
        },
    )


def step_train_gaps() -> None:
    """Re-run each ladder recipe with train-fold AUC. Does not change models."""
    X, y = load_gmsc()
    optuna_step = _prev("optuna")
    xgb_overrides, rf_overrides = _optuna_overrides(optuna_step["best_params"])
    jobs = [
        {
            "key": "class_weight",
            "label": "train-gap class_weight (also SHAP: all features kept)",
            "imbalance": "class_weight",
            "flags": dict(KEPT_FLAGS),
        },
        {
            "key": "optuna",
            "label": "train-gap Optuna best params, 0.6/0.4 vote",
            "imbalance": "class_weight",
            "flags": dict(KEPT_FLAGS),
            "xgb_overrides": xgb_overrides,
            "rf_overrides": rf_overrides,
            "weights": ENSEMBLE_WEIGHTS,
        },
        {
            "key": "baseline",
            "label": "train-gap baseline SMOTE",
            "imbalance": "smote",
            "flags": {
                "income_missing_flag": False,
                "recode_dpd_sentinel": False,
                "winsorize_util": False,
            },
        },
        {
            "key": "a_income_missing",
            "label": "train-gap (a) income_missing",
            "imbalance": "smote",
            "flags": {
                "income_missing_flag": True,
                "recode_dpd_sentinel": False,
                "winsorize_util": False,
            },
        },
        {
            "key": "b_dpd_sentinel",
            "label": "train-gap (b) DPD sentinel recode",
            "imbalance": "smote",
            "flags": {
                "income_missing_flag": False,
                "recode_dpd_sentinel": True,
                "winsorize_util": False,
            },
        },
        {
            "key": "c_winsorize_util",
            "label": "train-gap (c) util 99th",
            "imbalance": "smote",
            "flags": {
                "income_missing_flag": False,
                "recode_dpd_sentinel": False,
                "winsorize_util": True,
            },
        },
        {
            "key": "features_combined",
            "label": "train-gap kept features combined",
            "imbalance": "smote",
            "flags": dict(KEPT_FLAGS),
        },
    ]
    ladder = read_ladder()
    existing = next((s for s in ladder["steps"] if s.get("name") == "train_gaps"), {"gaps": {}})
    gaps = dict(existing.get("gaps") or {})
    for job in jobs:
        if job["key"] in gaps:
            print(f"skip {job['key']}: already recorded")
            continue
        mean_auc, std_auc, mean_f1, folds, _ = cross_validate_gmsc(
            X,
            y,
            job["label"],
            imbalance=job["imbalance"],
            xgb_overrides=job.get("xgb_overrides"),
            rf_overrides=job.get("rf_overrides"),
            weights=job.get("weights", ENSEMBLE_WEIGHTS),
            score_train=True,
            **job["flags"],
        )
        train_mean = float(np.mean([fold["train_auc"] for fold in folds]))
        gaps[job["key"]] = {
            "test_auc_mean": mean_auc,
            "test_auc_std": std_auc,
            "train_auc_mean": train_mean,
            "train_test_gap": train_mean - mean_auc,
            "f1_mean": mean_f1,
            "per_fold": folds,
        }
        write_step("train_gaps", {"gaps": gaps})
    final = _prev("final")
    gaps["blend_final"] = {
        "test_auc_mean": final["auc_roc_mean"],
        "test_auc_std": final["auc_roc_std"],
        "train_auc_mean": final["train_auc_mean"],
        "train_test_gap": final["train_test_gap"],
        "note": "Copied from final: Optuna params + 0.55/0.45 blend. SHAP equals class_weight (no features dropped).",
        "per_fold": final["per_fold"],
    }
    write_step("train_gaps", {"gaps": gaps})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--step",
        required=True,
        choices=(
            "baseline",
            "features",
            "combined",
            "class_weight",
            "shap_rank",
            "optuna",
            "blend",
            "final",
            "train_gaps",
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    {
        "baseline": step_baseline,
        "features": step_features,
        "combined": step_combined,
        "class_weight": step_class_weight,
        "shap_rank": step_shap_rank,
        "optuna": step_optuna,
        "blend": step_blend,
        "final": step_final,
        "train_gaps": step_train_gaps,
    }[args.step]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
