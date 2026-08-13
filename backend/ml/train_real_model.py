"""Train the ForiFlow SME credit model on real loan performance data.

Run from the ``backend`` directory::

    python -m ml.train_real_model

Pipeline
--------
1. Load ``credit_risk_dataset.csv`` and ``Loan_default.csv`` and print an
   exploration report (shape, dtypes, missing values, target balance, and the
   default rate behind every categorical level).
2. Map each dataset onto the ForiFlow feature space defined in :mod:`ml.features`.
3. Build three candidate training sets and let 5-fold cross-validation decide
   which to keep: each dataset on its own, plus the two combined over the
   features they genuinely share.
4. Fit a StandardScaler + SMOTE + (XGBoost, RandomForest) soft-voting ensemble
   on the winning candidate, with SMOTE applied inside every fold.
5. Build SHAP TreeExplainers in probability space so contributions convert
   directly into ForiFlow score points, and assert additivity.
6. Persist the model, scaler, explainers, feature names and clip bounds.

Why candidates are compared rather than blindly merged
------------------------------------------------------
The two files describe different populations and do not carry the same columns:
``credit_risk_dataset.csv`` has no tenure and no existing-debt column at all.
Merging on the union would leave those columns wholly imputed for 32k rows,
which lets the model recover *which dataset a row came from* and exploit the gap
between their default rates (roughly 22% versus 12%). That inflates
cross-validation without improving live accuracy, so the combined candidate is
restricted to the true column intersection and has to win on merit.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from ml.features import (
    FEATURE_NAMES,
    FEATURE_NAMES_PATH,
    MODEL_PATH,
    SCALER_PATH,
    SHAP_EXPLAINER_PATH,
    DATA_DIR,
)
from ml.shap_utils import expected_positive_value, positive_class_shap

RANDOM_STATE = 42
N_SPLITS = 5
TARGET = "target"

# Candidate selection runs on a stratified subsample to keep the search quick;
# the winner is then cross-validated and fitted on its full data.
MAX_SELECTION_ROWS = 60_000

# Rows sampled as the SHAP interventional background distribution. Interventional
# TreeSHAP cost scales with this, and the forest's 70k leaves make it the dominant
# term in request latency, so it is kept well below shap's 100-row masker default.
SHAP_BACKGROUND_ROWS = 50

# Soft-voting weights: XGBoost usually ranks better on tabular credit data,
# while the forest contributes calibration stability.
ENSEMBLE_WEIGHTS = (0.6, 0.4)

# ForiFlow's 0-100 payment history scale has only two supportable levels on this
# data: a clean bureau record and a default on file. Serving clips live scores into
# this range, so an ECIB score either side of the midpoint reads as one or other.
CLEAN_HISTORY_SCORE = 80.0
ADVERSE_HISTORY_SCORE = 25.0

# Direction each feature is allowed to push the predicted default probability.
# Constraining the gradient-boosted member keeps explanations defensible under
# SBP adverse-action review: a stronger repayment record can never be shown as
# increasing risk. Random forests cannot take these constraints, which is part of
# why the forest carries the smaller voting weight. Tenure is left unconstrained
# because a longer tenure both lowers the installment and extends the exposure.
FEATURE_MONOTONE_CONSTRAINTS: dict[str, int] = {
    "loan_to_income": 1,
    "installment_to_income": 1,
    "debt_service_to_income": 1,
    "payment_history_score": -1,
    "years_in_operation": -1,
    "tenure_months": 0,
}


def banner(title: str) -> None:
    """Print a section heading."""
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# ---------------------------------------------------------------------------
# 1. Loading and exploration
# ---------------------------------------------------------------------------


def load_datasets() -> dict[str, pd.DataFrame]:
    """Read both CSV files, failing loudly if either is missing."""
    paths = {
        "credit_risk": DATA_DIR / "credit_risk_dataset.csv",
        "loan_default": DATA_DIR / "Loan_default.csv",
    }
    frames: dict[str, pd.DataFrame] = {}
    for name, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f"Expected dataset at {path}")
        frames[name] = pd.read_csv(path)
        print(f"Loaded {name:<13} {path.name:<26} rows={len(frames[name]):>7,}")
    return frames


def explore(name: str, df: pd.DataFrame, target: str) -> None:
    """Print shape, dtypes, missing values and target balance for one dataset."""
    banner(f"EXPLORATION — {name}")
    print(f"Shape: {df.shape[0]:,} rows x {df.shape[1]} columns\n")

    summary = pd.DataFrame(
        {
            "dtype": df.dtypes.astype(str),
            "missing": df.isna().sum(),
            "missing_pct": (df.isna().mean() * 100).round(2),
            "unique": df.nunique(),
        }
    )
    print("Columns:")
    print(summary.to_string())

    positives = int(df[target].sum())
    print(
        f"\nTarget '{target}': {positives:,} defaults / {len(df):,} rows "
        f"= {positives / len(df) * 100:.2f}% positive class"
    )

    numeric = df.select_dtypes(include="number")
    print("\nNumeric summary:")
    print(numeric.describe().T[["mean", "std", "min", "50%", "max"]].round(2).to_string())


def report_categorical_encodings(name: str, df: pd.DataFrame, target: str) -> None:
    """Ordinal-encode categorical columns and report their default rates.

    The encodings are printed rather than fed to the model: none of these columns
    (home ownership, education, employment type, loan purpose, ...) exist on the
    ForiFlow intake form, so serving them would require inventing a value for
    every live applicant. The one exception is handled in the mapping step, where
    ``cb_person_default_on_file`` feeds the payment history score.
    """
    categorical = df.select_dtypes(include=["object", "category"]).columns.tolist()
    categorical = [column for column in categorical if df[column].nunique() <= 25]
    if not categorical:
        print("\nNo categorical columns to encode.")
        return

    print(f"\nCategorical encodings for {name} (ordinal codes and default rates):")
    for column in categorical:
        codes = {level: index for index, level in enumerate(sorted(df[column].dropna().unique()))}
        rates = df.groupby(column, observed=True)[target].mean().sort_values(ascending=False)
        rendered = ", ".join(
            f"{level}={codes[level]} ({rate * 100:.1f}%)" for level, rate in rates.items()
        )
        print(f"  {column}: {rendered}")
    print(
        "  -> Excluded from the served schema: the ForiFlow application form does\n"
        "     not collect these fields, so they cannot be supplied at inference."
    )


# ---------------------------------------------------------------------------
# 2. Mapping onto the ForiFlow feature space
# ---------------------------------------------------------------------------


def map_credit_risk(df: pd.DataFrame) -> pd.DataFrame:
    """Map ``credit_risk_dataset.csv`` onto ForiFlow features.

    Available: loan amount, annual income, employment length, credit history
    length and a prior-default flag.
    Absent: tenure and any existing-debt measure, so ``installment_to_income``,
    ``debt_service_to_income`` and ``tenure_months`` cannot be built.

    ``payment_history_score`` is bridged from the prior-default flag alone, which
    is the only genuine repayment-behaviour signal here: a default on file carries
    a 37.8% default rate against 18.4% for a clean record. Credit history *length*
    is deliberately excluded even though it is available, because within clean
    records default risk is flat across it (20.0% at two years versus 16-18% at
    fifteen, correlation -0.018). Folding it in previously produced a score the
    model could only fit as noise, and it penalised applicants with excellent
    repayment records — indefensible in an adverse-action letter. The cost is
    granularity: the data supports only a clean/adverse distinction, so ECIB
    scores either side of the midpoint are read as exactly that.
    """
    income = df["person_income"].replace(0, np.nan)

    prior_default = df["cb_person_default_on_file"].map({"Y": 1, "N": 0}).fillna(0)
    payment_history = np.where(prior_default == 1, ADVERSE_HISTORY_SCORE, CLEAN_HISTORY_SCORE)

    mapped = pd.DataFrame(
        {
            "loan_to_income": df["loan_amnt"] / income,
            "payment_history_score": payment_history,
            # Reported in years; a handful of rows carry impossible values such
            # as 123 years, which the clip bounds remove.
            "years_in_operation": df["person_emp_length"],
            TARGET: df["loan_status"].astype(int),
        }
    )
    return mapped


def map_loan_default(df: pd.DataFrame) -> pd.DataFrame:
    """Map ``Loan_default.csv`` onto ForiFlow features.

    This file carries every feature in the schema: loan amount, annual income,
    loan term, months employed, a 300-850 credit score and ``DTIRatio`` as a
    monthly debt-service ratio.
    """
    income = df["Income"].replace(0, np.nan)
    monthly_income = income / 12.0
    term = df["LoanTerm"].clip(lower=1)
    monthly_installment = df["LoanAmount"] / term

    mapped = pd.DataFrame(
        {
            "loan_to_income": df["LoanAmount"] / income,
            "installment_to_income": monthly_installment / monthly_income,
            "debt_service_to_income": df["DTIRatio"],
            # Rescale the 300-850 bureau score onto ForiFlow's 0-100 scale.
            "payment_history_score": ((df["CreditScore"] - 300) / 550 * 100).clip(0, 100),
            "years_in_operation": df["MonthsEmployed"] / 12.0,
            "tenure_months": term.astype(float),
            TARGET: df["Default"].astype(int),
        }
    )
    return mapped


def impute_medians(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """Fill missing feature values with the column median."""
    filled = df.copy()
    for column in features:
        missing = int(filled[column].isna().sum())
        if missing:
            median = float(filled[column].median())
            filled[column] = filled[column].fillna(median)
            print(f"  imputed {column:<24} {missing:>7,} missing -> median {median:.4f}")
    return filled


def learn_clips(df: pd.DataFrame, features: list[str]) -> dict[str, list[float]]:
    """Learn 1st/99th percentile clip bounds from the training data."""
    clips: dict[str, list[float]] = {}
    for column in features:
        lower = float(df[column].quantile(0.01))
        upper = float(df[column].quantile(0.99))
        if upper <= lower:
            upper = lower + 1e-6
        clips[column] = [lower, upper]
    return clips


def apply_clip_frame(
    df: pd.DataFrame, clips: dict[str, list[float]]
) -> pd.DataFrame:
    """Clip a frame's feature columns to the learned bounds."""
    clipped = df.copy()
    for column, (lower, upper) in clips.items():
        clipped[column] = clipped[column].clip(lower, upper)
    return clipped


# ---------------------------------------------------------------------------
# 3. Candidates and model construction
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """One training set under consideration."""

    name: str
    features: list[str]
    frame: pd.DataFrame
    note: str
    cv_auc: float = 0.0
    cv_auc_std: float = 0.0
    cv_f1: float = 0.0
    fold_scores: list[dict[str, float]] = field(default_factory=list)


def build_candidates(mapped: dict[str, pd.DataFrame]) -> list[Candidate]:
    """Assemble the candidate training sets, imputing and clipping each."""
    credit_risk = mapped["credit_risk"]
    loan_default = mapped["loan_default"]

    shared = [
        column
        for column in FEATURE_NAMES
        if column in credit_risk.columns and column in loan_default.columns
    ]
    print(f"\nFeatures shared by both datasets: {shared}")

    combined = pd.concat(
        [credit_risk[shared + [TARGET]], loan_default[shared + [TARGET]]],
        ignore_index=True,
    )

    specs = [
        (
            "loan_default_full",
            [column for column in FEATURE_NAMES if column in loan_default.columns],
            loan_default,
            "255k rows, all 6 features genuinely present",
        ),
        (
            "credit_risk_shared",
            shared,
            credit_risk,
            "32k rows, limited to the 3 shared features",
        ),
        (
            "combined_shared",
            shared,
            combined,
            "288k rows over the true column intersection (no fabricated columns)",
        ),
    ]

    candidates: list[Candidate] = []
    for name, features, frame, note in specs:
        print(f"\n{name}: {note}")
        working = frame[features + [TARGET]].copy()
        working = impute_medians(working, features)
        clips = learn_clips(working, features)
        working = apply_clip_frame(working, clips)
        candidates.append(Candidate(name=name, features=features, frame=working, note=note))
    return candidates


def build_ensemble(features: list[str]) -> VotingClassifier:
    """Create the XGBoost + RandomForest soft-voting ensemble.

    ``features`` fixes the column order so the monotone constraints line up with
    the columns the booster actually receives.
    """
    constraints = tuple(FEATURE_MONOTONE_CONSTRAINTS[name] for name in features)
    xgb = XGBClassifier(
        monotone_constraints=constraints,
        n_estimators=300,
        max_depth=5,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        min_child_weight=5,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        # Every feature is numeric. XGBoost >= 3.0 enables categorical support by
        # default, and shap then refuses to build interventional TreeExplainers
        # even when no categorical split exists.
        enable_categorical=False,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    forest = RandomForestClassifier(
        n_estimators=250,
        max_depth=12,
        min_samples_leaf=40,
        max_features="sqrt",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    return VotingClassifier(
        estimators=[("xgb", xgb), ("rf", forest)],
        voting="soft",
        weights=list(ENSEMBLE_WEIGHTS),
    )


def build_pipeline(features: list[str]) -> ImbPipeline:
    """Scaler -> SMOTE -> ensemble, so SMOTE only ever sees training folds."""
    return ImbPipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=RANDOM_STATE, k_neighbors=5)),
            ("model", build_ensemble(features)),
        ]
    )


def cross_validate(
    X: pd.DataFrame, y: pd.Series, label: str
) -> tuple[float, float, float, list[dict[str, float]]]:
    """Run stratified 5-fold CV, printing AUC-ROC and F1 per fold."""
    splitter = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    folds: list[dict[str, float]] = []

    print(f"\n{label}: {N_SPLITS}-fold cross-validation on {len(X):,} rows")
    print(f"  {'fold':<6}{'AUC-ROC':>10}{'F1':>10}{'PR-AUC':>10}{'seconds':>10}")

    for index, (train_index, test_index) in enumerate(splitter.split(X, y), start=1):
        started = time.perf_counter()
        pipeline = build_pipeline(list(X.columns))
        pipeline.fit(X.iloc[train_index], y.iloc[train_index])

        probabilities = pipeline.predict_proba(X.iloc[test_index])[:, 1]
        predictions = (probabilities >= 0.5).astype(int)
        y_test = y.iloc[test_index]

        scores = {
            "auc": roc_auc_score(y_test, probabilities),
            "f1": f1_score(y_test, predictions, zero_division=0),
            "pr_auc": average_precision_score(y_test, probabilities),
            "seconds": time.perf_counter() - started,
        }
        folds.append(scores)
        print(
            f"  {index:<6}{scores['auc']:>10.4f}{scores['f1']:>10.4f}"
            f"{scores['pr_auc']:>10.4f}{scores['seconds']:>10.1f}"
        )

    auc_values = [fold["auc"] for fold in folds]
    f1_values = [fold["f1"] for fold in folds]
    mean_auc, std_auc = float(np.mean(auc_values)), float(np.std(auc_values))
    mean_f1 = float(np.mean(f1_values))
    print(
        f"  mean  {mean_auc:>10.4f}{mean_f1:>10.4f}"
        f"{np.mean([fold['pr_auc'] for fold in folds]):>10.4f}"
    )
    print(f"  AUC-ROC {mean_auc:.4f} +/- {std_auc:.4f} | F1 {mean_f1:.4f}")
    return mean_auc, std_auc, mean_f1, folds


def report_score_distribution(probabilities: np.ndarray) -> dict[str, float]:
    """Report how hold-out applicants spread across the ForiFlow policy bands.

    ``risk_score`` is ``100 * (1 - PD)``, and the ensemble is trained on
    SMOTE-balanced data, so its probabilities are calibrated to a 50% prior. That
    is what keeps scores spread across the full 0-100 range instead of bunching
    near the portfolio's true default rate and approving everyone.
    """
    scores = 100.0 * (1.0 - probabilities)

    rejected = float((scores <= 40).mean())
    review = float(((scores > 40) & (scores <= 70)).mean())
    approved = float((scores > 70).mean())

    print("\nHold-out score distribution (score = 100 * (1 - PD))")
    print(f"  min {scores.min():.1f} | p25 {np.percentile(scores, 25):.1f} | "
          f"median {np.median(scores):.1f} | p75 {np.percentile(scores, 75):.1f} | "
          f"max {scores.max():.1f}")
    print("  policy mix:")
    print(f"    Rejected      (0-40)   {rejected * 100:>5.1f}%")
    print(f"    Manual Review (41-70)  {review * 100:>5.1f}%")
    print(f"    Approved      (71-100) {approved * 100:>5.1f}%")

    return {
        "score_min": float(scores.min()),
        "score_median": float(np.median(scores)),
        "score_max": float(scores.max()),
        "share_rejected": rejected,
        "share_manual_review": review,
        "share_approved": approved,
    }


def stratified_sample(frame: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    """Take a stratified subsample when a frame is larger than ``max_rows``."""
    if len(frame) <= max_rows:
        return frame
    sample, _ = train_test_split(
        frame,
        train_size=max_rows,
        stratify=frame[TARGET],
        random_state=RANDOM_STATE,
    )
    return sample.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 4. SHAP
# ---------------------------------------------------------------------------


def build_shap_explainers(
    model: VotingClassifier, background: np.ndarray, feature_names: list[str]
) -> dict:
    """Build one TreeExplainer per ensemble member, in probability space.

    Explaining probabilities (rather than log-odds) means a contribution can be
    multiplied by 100 and read directly as ForiFlow score points. Shapley values
    are additive across a weighted average of models, so averaging the members'
    contributions with the voting weights exactly explains the ensemble's
    averaged probability.
    """
    import shap

    explainers: dict[str, object] = {}
    output_space = "probability"

    for name, estimator in zip(("xgb", "rf"), model.estimators_, strict=True):
        try:
            explainers[name] = shap.TreeExplainer(
                estimator,
                data=background,
                model_output="probability",
                feature_perturbation="interventional",
            )
        except Exception as error:  # pragma: no cover - depends on shap version
            print(f"  probability-space SHAP unavailable for {name}: {error}")
            print("  falling back to log-odds margins for both members")
            output_space = "log_odds"
            explainers = {
                member_name: shap.TreeExplainer(member)
                for member_name, member in zip(("xgb", "rf"), model.estimators_, strict=True)
            }
            break

    return {
        "explainers": explainers,
        "weights": {"xgb": ENSEMBLE_WEIGHTS[0], "rf": ENSEMBLE_WEIGHTS[1]},
        "output_space": output_space,
        "feature_names": feature_names,
    }


def verify_additivity(
    bundle: dict, model: VotingClassifier, samples: np.ndarray
) -> float:
    """Check that base value + contributions reproduces the ensemble PD.

    Returns the maximum absolute error across the sample.
    """
    weights = bundle["weights"]
    total = np.zeros(len(samples))
    base = 0.0

    for name, explainer in bundle["explainers"].items():
        contributions = positive_class_shap(explainer.shap_values(samples))
        total += weights[name] * contributions.sum(axis=1)
        base += weights[name] * expected_positive_value(explainer)

    reconstructed = base + total
    actual = model.predict_proba(samples)[:, 1]
    error = float(np.max(np.abs(reconstructed - actual)))
    print(f"  SHAP additivity check: max |reconstructed - predicted| = {error:.6f}")
    return error


# ---------------------------------------------------------------------------
# 5. Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        choices=("credit_risk_shared", "loan_default_full", "combined_shared"),
        help=(
            "Skip candidate selection and retrain on this dataset. Use for routine "
            "retrains once the comparison has been run; the previous comparison is "
            "carried into the new metadata for traceability."
        ),
    )
    return parser.parse_args(argv)


def inherited_comparison() -> list[dict] | None:
    """Read the candidate comparison recorded by a previous full run."""
    if not FEATURE_NAMES_PATH.exists():
        return None
    try:
        with FEATURE_NAMES_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle).get("candidates")
    except (OSError, json.JSONDecodeError):
        return None


def main(argv: list[str] | None = None) -> int:
    """Run the full training pipeline and persist the artefacts."""
    args = parse_args(argv)
    started = time.perf_counter()
    banner("FORIFLOW MODEL TRAINING — real loan performance data")

    raw = load_datasets()

    explore("credit_risk_dataset.csv", raw["credit_risk"], "loan_status")
    report_categorical_encodings("credit_risk_dataset.csv", raw["credit_risk"], "loan_status")

    explore("Loan_default.csv", raw["loan_default"], "Default")
    report_categorical_encodings("Loan_default.csv", raw["loan_default"], "Default")

    banner("FEATURE MAPPING")
    mapped = {
        "credit_risk": map_credit_risk(raw["credit_risk"]),
        "loan_default": map_loan_default(raw["loan_default"]),
    }
    for name, frame in mapped.items():
        built = [column for column in FEATURE_NAMES if column in frame.columns]
        missing = [column for column in FEATURE_NAMES if column not in frame.columns]
        print(f"\n{name}: built {len(built)}/{len(FEATURE_NAMES)} features -> {built}")
        if missing:
            print(f"  no source column for -> {missing}")

    banner("CANDIDATE TRAINING SETS")
    candidates = build_candidates(mapped)

    by_name = {candidate.name: candidate for candidate in candidates}
    comparison: list[dict] = []

    if args.dataset:
        banner("CANDIDATE SELECTION SKIPPED")
        winner = by_name[args.dataset]
        print(f"--dataset {args.dataset}: reusing a previously selected training set.")
        comparison = inherited_comparison() or []
        if comparison:
            print("Carrying the recorded comparison into the new metadata.")
        else:
            print("No previous comparison found; metadata will record none.")
    else:
        banner("CANDIDATE SELECTION (5-fold CV on a stratified subsample)")
        print(f"Subsample cap: {MAX_SELECTION_ROWS:,} rows per candidate")
        for candidate in candidates:
            sample = stratified_sample(candidate.frame, MAX_SELECTION_ROWS)
            auc, std, f1, folds = cross_validate(
                sample[candidate.features], sample[TARGET], candidate.name
            )
            candidate.cv_auc, candidate.cv_auc_std, candidate.cv_f1 = auc, std, f1
            candidate.fold_scores = folds

        ranked = sorted(candidates, key=lambda item: item.cv_auc, reverse=True)
        banner("CANDIDATE RANKING")
        print(f"{'candidate':<22}{'features':>10}{'rows':>10}{'AUC-ROC':>10}{'F1':>10}")
        for candidate in ranked:
            print(
                f"{candidate.name:<22}{len(candidate.features):>10}"
                f"{len(candidate.frame):>10,}{candidate.cv_auc:>10.4f}"
                f"{candidate.cv_f1:>10.4f}"
            )
        winner = ranked[0]
        comparison = [
            {
                "name": candidate.name,
                "features": candidate.features,
                "rows": int(len(candidate.frame)),
                "auc_roc": candidate.cv_auc,
                "f1": candidate.cv_f1,
                "note": candidate.note,
            }
            for candidate in ranked
        ]

    print(f"\nSelected: {winner.name} ({winner.note})")

    banner(f"DEFINITIVE 5-FOLD CROSS-VALIDATION — {winner.name} (full data)")
    X_all = winner.frame[winner.features]
    y_all = winner.frame[TARGET]
    final_auc, final_auc_std, final_f1, final_folds = cross_validate(
        X_all, y_all, f"{winner.name} (full)"
    )

    banner("FINAL FIT AND HOLD-OUT EVALUATION")
    X_train, X_test, y_train, y_test = train_test_split(
        X_all, y_all, test_size=0.2, stratify=y_all, random_state=RANDOM_STATE
    )
    print(f"Train {len(X_train):,} rows | Hold-out {len(X_test):,} rows")

    # Fitted on a plain array: serving builds feature vectors positionally from
    # feature_names.json, and a scaler that remembers DataFrame column names would
    # warn on every request.
    scaler = StandardScaler().fit(X_train.to_numpy())
    X_train_scaled = scaler.transform(X_train.to_numpy())
    X_test_scaled = scaler.transform(X_test.to_numpy())

    smote = SMOTE(random_state=RANDOM_STATE, k_neighbors=5)
    X_resampled, y_resampled = smote.fit_resample(X_train_scaled, y_train)
    print(
        f"SMOTE: {len(X_train_scaled):,} -> {len(X_resampled):,} rows "
        f"(positives {int(y_train.sum()):,} -> {int(y_resampled.sum()):,})"
    )

    model = build_ensemble(winner.features)
    model.fit(X_resampled, y_resampled)

    holdout_probabilities = model.predict_proba(X_test_scaled)[:, 1]
    holdout_predictions = (holdout_probabilities >= 0.5).astype(int)
    holdout = {
        "auc": float(roc_auc_score(y_test, holdout_probabilities)),
        "f1": float(f1_score(y_test, holdout_predictions, zero_division=0)),
        "pr_auc": float(average_precision_score(y_test, holdout_probabilities)),
        "brier": float(brier_score_loss(y_test, holdout_probabilities)),
    }
    print(
        f"Hold-out AUC-ROC {holdout['auc']:.4f} | F1 {holdout['f1']:.4f} | "
        f"PR-AUC {holdout['pr_auc']:.4f} | Brier {holdout['brier']:.4f}"
    )
    holdout.update(report_score_distribution(holdout_probabilities))

    banner("SHAP EXPLAINERS")
    rng = np.random.default_rng(RANDOM_STATE)
    background_index = rng.choice(
        len(X_resampled), size=min(SHAP_BACKGROUND_ROWS, len(X_resampled)), replace=False
    )
    background = np.asarray(X_resampled)[background_index]
    bundle = build_shap_explainers(model, background, winner.features)
    print(f"  output space: {bundle['output_space']}")

    check_sample = X_test_scaled[:25]
    additivity_error = (
        verify_additivity(bundle, model, check_sample)
        if bundle["output_space"] == "probability"
        else float("nan")
    )

    banner("SAVING ARTEFACTS")
    import joblib

    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    joblib.dump(bundle, SHAP_EXPLAINER_PATH)

    metadata = {
        "feature_names": winner.features,
        "feature_clips": learn_clips(winner.frame, winner.features),
        "dataset": winner.name,
        "dataset_note": winner.note,
        "rows": int(len(winner.frame)),
        "default_rate": float(y_all.mean()),
        "shap_output_space": bundle["output_space"],
        "shap_additivity_max_error": additivity_error,
        "ensemble_weights": {"xgb": ENSEMBLE_WEIGHTS[0], "rf": ENSEMBLE_WEIGHTS[1]},
        "monotone_constraints": {
            name: FEATURE_MONOTONE_CONSTRAINTS[name] for name in winner.features
        },
        "cross_validation": {
            "folds": N_SPLITS,
            "auc_roc_mean": final_auc,
            "auc_roc_std": final_auc_std,
            "f1_mean": final_f1,
            "per_fold": final_folds,
        },
        "holdout": holdout,
        "candidates": comparison,
        "selection_skipped": bool(args.dataset),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with FEATURE_NAMES_PATH.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)

    for path in (MODEL_PATH, SCALER_PATH, SHAP_EXPLAINER_PATH, FEATURE_NAMES_PATH):
        print(f"  saved {path.name:<24} {path.stat().st_size / 1024:>8.1f} KB")

    print(f"\nCompleted in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
