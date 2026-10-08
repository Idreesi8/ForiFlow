"""Train the ForiFlow demonstration credit model on public consumer loan data.

Run from the ``backend`` directory, then evaluate once::

    python -m ml.train_real_model
    python -m ml.evaluate_model

Since 2.2 :func:`main` follows the leakage-free protocol in :mod:`ml.pipeline`:
split first (train 60% / validation 20% / final test 20%, stratified, seed 42),
learn imputation medians, clip bounds and the scaler on the training split only,
apply SMOTE to the training rows only, choose and fit the calibrator on the
validation split, and leave the final test set to ``ml.evaluate_model``.

The data is ``credit_risk_dataset.csv``: public consumer loans, not Pakistani
SME lending data. The model is a demonstration model and is not validated for
SME credit decisions.

The candidate functions below (:func:`build_candidates`, :func:`cross_validate`)
are the pre-2.2 dataset-selection path. They impute and clip on a whole file
and are kept only for the research scripts (``ml.auc_ladder*``); the served
model is not built with them.
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
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from ml.features import (
    ADVERSE_HISTORY_SCORE,
    CLEAN_HISTORY_SCORE,
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
# data: a clean bureau record and a default on file. Serving snaps live scores to
# these levels at the midpoint (ml.features.snap_payment_history), so an ECIB
# score either side of 52.5 reads as one or the other.

# Direction each feature is allowed to push the predicted default probability.
# Both members are constrained (XGBoost ``monotone_constraints``, scikit-learn
# >= 1.4 ``monotonic_cst``), and a weighted average of monotone functions is
# monotone, so the served score can never fall because an applicant has more
# years in operation, a stronger repayment record or a smaller facility. That
# keeps explanations defensible under SBP adverse-action review. Before the
# forest was constrained, a business trading six years scored 10 points below
# one trading five. Tenure is left unconstrained because a longer tenure both
# lowers the installment and extends the exposure.
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


DATASET_FILES: dict[str, str] = {
    "credit_risk": "credit_risk_dataset.csv",
    "loan_default": "Loan_default.csv",
}

# Source datasets each training set needs. A routine ``--dataset`` retrain only
# reads the files it actually uses, so retraining the served model does not
# require the 25 MB Loan_default.csv.
DATASETS_NEEDED: dict[str | None, tuple[str, ...]] = {
    None: ("credit_risk", "loan_default"),
    "credit_risk_shared": ("credit_risk",),
    "loan_default_full": ("loan_default",),
    "combined_shared": ("credit_risk", "loan_default"),
}

# Features present in both public datasets. Equal to the column intersection
# computed in :func:`build_candidates`, which asserts it whenever both files are
# loaded; used on its own when only credit_risk_dataset.csv is available.
SHARED_FEATURES: list[str] = ["loan_to_income", "payment_history_score", "years_in_operation"]


def load_datasets(names: tuple[str, ...] = ("credit_risk", "loan_default")) -> dict[str, pd.DataFrame]:
    """Read the requested CSV files, failing loudly if one is missing.

    Download links for both files are in backend/README.md ("Training data").
    """
    frames: dict[str, pd.DataFrame] = {}
    for name in names:
        path = DATA_DIR / DATASET_FILES[name]
        if not path.exists():
            raise FileNotFoundError(
                f"Expected dataset at {path}. See backend/README.md, 'Training data', "
                "for where to download it."
            )
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
    """Assemble the candidate training sets, imputing and clipping each.

    Only the sets whose source files were loaded are built, so a
    ``--dataset credit_risk_shared`` retrain needs credit_risk_dataset.csv alone.
    """
    credit_risk = mapped.get("credit_risk")
    loan_default = mapped.get("loan_default")

    if credit_risk is not None and loan_default is not None:
        shared = [
            column
            for column in FEATURE_NAMES
            if column in credit_risk.columns and column in loan_default.columns
        ]
        assert shared == SHARED_FEATURES, f"shared features changed: {shared}"
        combined = pd.concat(
            [credit_risk[shared + [TARGET]], loan_default[shared + [TARGET]]],
            ignore_index=True,
        )
    else:
        shared = list(SHARED_FEATURES)
        combined = None
    print(f"\nFeatures shared by both datasets: {shared}")

    specs = [
        (
            "loan_default_full",
            [column for column in FEATURE_NAMES if column in loan_default.columns]
            if loan_default is not None
            else [],
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
        if frame is None:
            continue
        print(f"\n{name}: {note}")
        working = frame[features + [TARGET]].copy()
        working = impute_medians(working, features)
        clips = learn_clips(working, features)
        working = apply_clip_frame(working, clips)
        candidates.append(Candidate(name=name, features=features, frame=working, note=note))
    return candidates


def scale_pos_weight_from(y: pd.Series | np.ndarray) -> float:
    """neg/pos ratio for XGBoost ``scale_pos_weight`` on a training fold."""
    values = np.asarray(y)
    n_pos = float(values.sum())
    n_neg = float(len(values) - n_pos)
    if n_pos == 0:
        return 1.0
    return n_neg / n_pos


def build_ensemble(
    features: list[str],
    *,
    scale_pos_weight: float = 1.0,
    rf_class_weight: str | dict | None = None,
    xgb_overrides: dict | None = None,
    rf_overrides: dict | None = None,
    weights: tuple[float, float] = ENSEMBLE_WEIGHTS,
) -> VotingClassifier:
    """Create the XGBoost + RandomForest soft-voting ensemble.

    ``features`` fixes the column order so the monotone constraints line up with
    the columns both members actually receive.
    """
    constraints = tuple(FEATURE_MONOTONE_CONSTRAINTS[name] for name in features)
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
        # Every feature is numeric. XGBoost >= 3.0 enables categorical support by
        # default, and shap then refuses to build interventional TreeExplainers
        # even when no categorical split exists.
        "enable_categorical": False,
        "random_state": RANDOM_STATE,
        "n_jobs": -1,
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
        "n_jobs": -1,
        # Same directions as the booster; see FEATURE_MONOTONE_CONSTRAINTS.
        "monotonic_cst": list(constraints),
    }
    if rf_overrides:
        rf_params.update(rf_overrides)
    xgb = XGBClassifier(**xgb_params)
    forest = RandomForestClassifier(**rf_params)
    return VotingClassifier(
        estimators=[("xgb", xgb), ("rf", forest)],
        voting="soft",
        weights=list(weights),
    )


def build_pipeline(
    features: list[str],
    *,
    y_train: pd.Series | np.ndarray | None = None,
    imbalance: str = "smote",
    xgb_overrides: dict | None = None,
    rf_overrides: dict | None = None,
    weights: tuple[float, float] = ENSEMBLE_WEIGHTS,
):
    """Build the train-time pipeline.

    ``imbalance='smote'`` is the production recipe (50/50 resample inside the
    fold). ``imbalance='class_weight'`` uses XGBoost ``scale_pos_weight`` and
    RandomForest ``class_weight='balanced'`` with no oversampling.
    """
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
        raise ValueError("class_weight mode needs y_train to set scale_pos_weight")
    spw = scale_pos_weight_from(y_train)
    from sklearn.pipeline import Pipeline as SkPipeline

    return SkPipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "model",
                build_ensemble(
                    features,
                    scale_pos_weight=spw,
                    rf_class_weight="balanced",
                    xgb_overrides=xgb_overrides,
                    rf_overrides=rf_overrides,
                    weights=weights,
                ),
            ),
        ]
    )


def cross_validate(
    X: pd.DataFrame,
    y: pd.Series,
    label: str,
    *,
    imbalance: str = "smote",
    xgb_overrides: dict | None = None,
    rf_overrides: dict | None = None,
    weights: tuple[float, float] = ENSEMBLE_WEIGHTS,
) -> tuple[float, float, float, list[dict[str, float]]]:
    """Run stratified 5-fold CV, printing AUC-ROC and F1 per fold."""
    splitter = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    folds: list[dict[str, float]] = []

    print(f"\n{label}: {N_SPLITS}-fold cross-validation on {len(X):,} rows")
    print(f"  {'fold':<6}{'AUC-ROC':>10}{'F1':>10}{'PR-AUC':>10}{'seconds':>10}")

    for index, (train_index, test_index) in enumerate(splitter.split(X, y), start=1):
        started = time.perf_counter()
        y_train = y.iloc[train_index]
        pipeline = build_pipeline(
            list(X.columns),
            y_train=y_train,
            imbalance=imbalance,
            xgb_overrides=xgb_overrides,
            rf_overrides=rf_overrides,
            weights=weights,
        )
        pipeline.fit(X.iloc[train_index], y_train)

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


def _history_levels(winner) -> dict[str, list[float]]:
    """Record the history levels when the winner learnt history as a binary flag."""
    if "payment_history_score" not in winner.features:
        return {}
    levels = sorted(float(v) for v in winner.frame["payment_history_score"].unique())
    return {"payment_history_levels": levels} if len(levels) == 2 else {}


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
        choices=("credit_risk_shared",),
        default="credit_risk_shared",
        help=(
            "The training set. Since 2.2 only credit_risk_shared is trained, under the "
            "leakage-free protocol of ml.pipeline. The dataset was chosen over "
            "loan_default_full and combined_shared in an earlier release (see "
            "'dataset_selection' in the metadata)."
        ),
    )
    return parser.parse_args(argv)


def inherited_comparison() -> list[dict] | None:
    """Read the candidate comparison recorded by a previous run."""
    if not FEATURE_NAMES_PATH.exists():
        return None
    try:
        with FEATURE_NAMES_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle).get("candidates")
    except (OSError, json.JSONDecodeError):
        return None


def previous_metrics() -> dict | None:
    """The served model's own figures before this run, for a before/after record."""
    if not FEATURE_NAMES_PATH.exists():
        return None
    try:
        previous = json.loads(FEATURE_NAMES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if "training_protocol_version" in previous:
        return previous.get("previous_model")
    cv = previous.get("cross_validation", {})
    holdout = previous.get("holdout", {})
    return {
        "trained_at": previous.get("trained_at"),
        "protocol": (
            "pre-2.2: medians and clip bounds learned on the whole file before an "
            "80/20 split; the same 20% hold-out reused for evaluation, fairness and "
            "band reports"
        ),
        "cv_auc_roc_mean": cv.get("auc_roc_mean"),
        "cv_auc_roc_std": cv.get("auc_roc_std"),
        "holdout_auc_roc": holdout.get("auc"),
        "holdout_pr_auc": holdout.get("pr_auc"),
        "holdout_f1": holdout.get("f1"),
        "holdout_brier_raw": holdout.get("brier"),
        "rows": previous.get("rows"),
    }


def model_config(features: list[str]) -> dict:
    """The exact learner settings, for the metadata."""
    ensemble = build_ensemble(features)
    members = dict(ensemble.estimators)

    def plain(params: dict) -> dict:
        return {
            key: (list(value) if isinstance(value, tuple) else value)
            for key, value in params.items()
            if isinstance(value, (int, float, str, bool, list, tuple, type(None)))
        }

    return {
        "ensemble": "soft voting, weights xgb 0.6 / rf 0.4",
        "xgboost": plain(members["xgb"].get_params()),
        "random_forest": plain(members["rf"].get_params()),
        "smote": {"k_neighbors": 5, "random_state": RANDOM_STATE, "applied_to": "scaled training rows only"},
        "scaler": "StandardScaler fitted on the training split",
        "logistic_regression_baseline": {"max_iter": 1000, "random_state": RANDOM_STATE},
    }


def main(argv: list[str] | None = None) -> int:
    """Train under the 2.2 protocol and persist the served artefacts.

    The final test set is split off but never read here; ``ml.evaluate_model``
    scores it once, afterwards.
    """
    from ml import pipeline
    from ml.data_quality import CREDIT_RISK_VALID_RANGES, data_quality_report, write_report

    args = parse_args(argv)
    started = time.perf_counter()
    banner("FORIFLOW MODEL TRAINING — leakage-free protocol (2.2)")
    before = previous_metrics()
    selection = inherited_comparison() or []

    prepared = pipeline.load_prepared()
    explore("credit_risk_dataset.csv", prepared.raw, "loan_status")
    print(f"\nExcluded before the split: {prepared.excluded}")

    features = list(pipeline.MODEL_FEATURES)
    frame = prepared.frame
    split = pipeline.split_rows(frame)
    split_info = split.describe(frame)
    print(f"\nSplit (seed {split.seed}): {split_info['rows']}")
    X_train, y_train = frame.loc[split.train, features], frame.loc[split.train, TARGET]
    X_val, y_val = frame.loc[split.validation, features], frame.loc[split.validation, TARGET]

    banner("5-FOLD CROSS-VALIDATION ON THE TRAINING SPLIT (everything refit per fold)")
    cv = {name: pipeline.cross_validate_training(name, X_train, y_train) for name in pipeline.MODEL_NAMES}
    for name in pipeline.MODEL_NAMES:
        if name != "ensemble":
            cv[name]["vs_ensemble"] = pipeline.paired_auc_test(
                [f["auc_roc"] for f in cv[name]["per_fold"]],
                [f["auc_roc"] for f in cv["ensemble"]["per_fold"]],
            )
        print(f"  {name:<20} AUC {cv[name]['auc_roc_mean']:.4f} ± {cv[name]['auc_roc_std']:.4f}")

    banner("FIT ON TRAINING, MEASURE ON VALIDATION")
    fitted = {}
    validation = {}
    for name in pipeline.MODEL_NAMES:
        fitted[name] = pipeline.build_training_pipeline(name, features).fit(X_train, y_train)
        probability = fitted[name].predict_proba(X_val)[:, 1]
        validation[name] = pipeline.classification_metrics(y_val.to_numpy(), probability)
        print(f"  {name:<20} AUC {validation[name]['auc_roc']:.4f}  Brier {validation[name]['brier']:.4f}")

    served = fitted["ensemble"]
    preprocess = served.named_steps["preprocess"]
    scaler = served.named_steps["scaler"]
    model = served.named_steps["model"]
    raw_val = served.predict_proba(X_val)[:, 1]

    banner("CALIBRATION (chosen and fitted on validation; display only)")
    calibration = pipeline.select_calibration(raw_val, y_val.to_numpy())
    oof = calibration.pop("out_of_fold_calibrated")
    print(f"  out-of-fold Brier: {calibration['selection']['brier_out_of_fold']}")
    print(f"  chosen: {calibration['method_label']}")
    validation_calibrated = (
        pipeline.classification_metrics(y_val.to_numpy(), oof) if oof is not None else None
    )

    banner("SHAP EXPLAINERS")
    X_train_scaled = scaler.transform(preprocess.transform(X_train))
    X_resampled, _ = SMOTE(random_state=RANDOM_STATE, k_neighbors=5).fit_resample(
        X_train_scaled, y_train
    )
    rng = np.random.default_rng(RANDOM_STATE)
    background_index = rng.choice(
        len(X_resampled), size=min(SHAP_BACKGROUND_ROWS, len(X_resampled)), replace=False
    )
    bundle = build_shap_explainers(model, np.asarray(X_resampled)[background_index], features)
    check = scaler.transform(preprocess.transform(X_val.iloc[:25]))
    additivity_error = (
        verify_additivity(bundle, model, check) if bundle["output_space"] == "probability" else float("nan")
    )

    banner("SAVING ARTEFACTS")
    import joblib

    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    joblib.dump(bundle, SHAP_EXPLAINER_PATH)
    trained_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    train_frame = frame.loc[split.train]
    levels = sorted(float(v) for v in train_frame["payment_history_score"].dropna().unique())

    metadata = {
        "feature_names": features,
        "feature_clips": preprocess.clips_,
        "feature_medians": preprocess.medians_,
        "dataset": args.dataset,
        "dataset_note": "public consumer loans, limited to the 3 features ForiFlow can supply",
        "dataset_identifier": pipeline.DATASET_IDENTIFIER,
        "dataset_type": pipeline.DATASET_TYPE,
        "dataset_type_label": pipeline.DATASET_TYPE_LABEL,
        "dataset_file": pipeline.DATASET_FILE,
        "dataset_sha256": prepared.dataset_sha256,
        "rows": int(len(frame)),
        "rows_in_file": prepared.rows_in_file,
        "excluded_rows": prepared.excluded,
        # The training split's default rate: what the calibrator maps towards.
        "default_rate": float(y_train.mean()),
        "random_seed": RANDOM_STATE,
        "split": split_info,
        "preprocessing": {
            "version": pipeline.PREPROCESSING_VERSION,
            "steps": [
                "drop exact duplicate rows of the raw file (before the split)",
                "map onto loan_to_income, payment_history_score, years_in_operation",
                "median imputation, medians learned on the training split",
                "clip to the training split's 1st/99th percentiles",
                "StandardScaler fitted on the training split",
                "SMOTE (k=5) on the scaled training rows only",
            ],
            "fitted_on": "training split only",
            "clip_quantiles": list(pipeline.CLIP_QUANTILES),
        },
        "model_config": model_config(features),
        "shap_output_space": bundle["output_space"],
        "shap_additivity_max_error": additivity_error,
        "shap_reference": {
            "rows": int(len(background_index)),
            "source": "random sample of the SMOTE-balanced (50/50) training rows",
            "description": (
                "Model reference baseline: the ensemble's expected score over this "
                "reference sample. It is not the average of a bank portfolio or of the "
                "public file, whose default rate is about 22%."
            ),
        },
        "ensemble_weights": {"xgb": ENSEMBLE_WEIGHTS[0], "rf": ENSEMBLE_WEIGHTS[1]},
        "monotone_constraints": {name: FEATURE_MONOTONE_CONSTRAINTS[name] for name in features},
        **({"payment_history_levels": levels} if len(levels) == 2 else {}),
        "cross_validation": {
            "scope": "training split only",
            "folds": pipeline.CV_FOLDS,
            "auc_roc_mean": cv["ensemble"]["auc_roc_mean"],
            "auc_roc_std": cv["ensemble"]["auc_roc_std"],
            "f1_mean": cv["ensemble"]["f1_mean"],
            "pr_auc_mean": cv["ensemble"]["pr_auc_mean"],
            "per_fold": cv["ensemble"]["per_fold"],
        },
        "validation": {
            "rows": int(len(y_val)),
            "evaluation_threshold": pipeline.EVALUATION_THRESHOLD,
            "ensemble_raw": validation["ensemble"],
            "ensemble_calibrated_out_of_fold": validation_calibrated,
            "baselines": {name: validation[name] for name in pipeline.MODEL_NAMES},
        },
        "calibration": calibration,
        "evaluation_threshold": {
            "raw_probability": pipeline.EVALUATION_THRESHOLD,
            "note": (
                "Model evaluation threshold, fixed before any result was seen and never "
                "tuned. Credit policy thresholds are separate and configurable."
            ),
        },
        "dataset_selection": {
            "note": (
                "credit_risk_shared was chosen over loan_default_full and combined_shared "
                "in release 1.x by 5-fold CV over each whole file, before this protocol "
                "existed. That choice between datasets is not re-run; no hyperparameter, "
                "threshold or calibrator of this model was chosen on the final test set."
            ),
            "candidates": selection,
        },
        "candidates": selection,
        "selection_skipped": True,
        "previous_model": before,
        "training_protocol_version": pipeline.TRAINING_PROTOCOL_VERSION,
        "trained_at": trained_at,
    }
    with FEATURE_NAMES_PATH.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)

    report = data_quality_report(
        pd.read_csv(pipeline.DATA_DIR / pipeline.DATASET_FILE),
        "loan_status",
        dataset_identifier=pipeline.DATASET_IDENTIFIER,
        dataset_type_label=pipeline.DATASET_TYPE_LABEL,
        dataset_sha256=prepared.dataset_sha256,
        valid_ranges=CREDIT_RISK_VALID_RANGES,
        excluded=prepared.excluded,
        preprocessing=metadata["preprocessing"]["steps"],
        learned_parameters={"medians": preprocess.medians_, "clip_bounds": preprocess.clips_},
        model_features=features,
        mapped=frame,
    )
    report["model_trained_at"] = trained_at
    write_report(report)

    comparison = {
        "dataset": args.dataset,
        "model_trained_at": trained_at,
        "rows": {"train": int(len(y_train)), "validation": int(len(y_val))},
        "features": features,
        "protocol": (
            "Same split, same train-only preprocessing (median, clip, scaler) and SMOTE "
            "on the training rows for every model. Cross-validation: 5 folds on the "
            "training split. Validation: models fitted on the training split. The final "
            "test figures are added once by ml.evaluate_model."
        ),
        "labels": pipeline.MODEL_LABELS,
        "models": {
            # Pre-2.2 key kept for the served model.
            ("served_ensemble_xgb_rf" if name == "ensemble" else name): {
                "cross_validation": cv[name],
                "validation": validation[name],
                # Flat CV figures for older clients.
                "auc_roc_mean": cv[name]["auc_roc_mean"],
                "auc_roc_std": cv[name]["auc_roc_std"],
                "pr_auc_mean": cv[name]["pr_auc_mean"],
                "f1_mean": cv[name]["f1_mean"],
                "brier_mean": cv[name]["brier_mean"],
                "vs_served": cv[name].get("vs_ensemble"),
            }
            for name in pipeline.MODEL_NAMES
        },
    }
    from ml.features import COMPARISON_PATH

    COMPARISON_PATH.write_text(json.dumps(comparison, indent=2), encoding="utf-8")

    for path in (MODEL_PATH, SCALER_PATH, SHAP_EXPLAINER_PATH, FEATURE_NAMES_PATH):
        print(f"  saved {path.name:<24} {path.stat().st_size / 1024:>8.1f} KB")
    print(f"\nCompleted in {time.perf_counter() - started:.1f}s. Now run: python -m ml.evaluate_model")
    return 0


if __name__ == "__main__":
    sys.exit(main())
