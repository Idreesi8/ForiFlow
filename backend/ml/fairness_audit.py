"""Check whether the served model treats groups of applicants differently.

Run from the ``backend`` directory, after :mod:`ml.evaluate_model`::

    python -m ml.fairness_audit

The model reads three inputs and none of them is age, housing, income or the
purpose of the loan. That does not make it neutral: an input can stand in for a
group (years in operation is short for the young), and a model that cannot see
something that matters will misprice the people it matters for.

This script takes the same 20% hold-out as the evaluation, joins each loan back
to four attributes of the public file that the model never saw, and reports for
every group:

* how often it is approved, and that rate against the best-treated group (the
  "four-fifths" screen used in fair-lending reviews);
* the probability of default the model gives the group against the default rate
  the group really had, which is the test that matters: a gap means the model is
  too harsh or too lenient for that group, whatever the approval rates are;
* the wrong decisions on each side: good payers rejected, defaulters approved.

Results are written to ``ml/fairness_audit.json``. The file has no gender, so
gender cannot be audited here. Nothing in this script changes the model.
"""

from __future__ import annotations

import json
import math
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from ml.evaluate_model import MANUAL_REVIEW_UPPER_BOUND, REJECT_UPPER_BOUND
from ml.features import (
    FAIRNESS_PATH,
    MODEL_PATH,
    SCALER_PATH,
    load_feature_metadata,
    load_model_evaluation,
)
from ml.train_real_model import (
    RANDOM_STATE,
    TARGET,
    build_candidates,
    load_datasets,
    map_credit_risk,
)

# A group smaller than this is reported but takes no part in any verdict.
MIN_GROUP_ROWS = 100
# Fair-lending screen: a group approved at under 80% of the best group's rate.
FOUR_FIFTHS = 0.80
# Two-sided 95% normal interval.
Z_95 = 1.96

AGE_EDGES = [0, 24, 34, 44, 200]
AGE_LABELS = ["Under 25", "25 to 34", "35 to 44", "45 and over"]
INCOME_LABELS = ["Lowest quarter", "Second quarter", "Third quarter", "Highest quarter"]
HOME_LABELS = {"RENT": "Rents", "MORTGAGE": "Mortgage", "OWN": "Owns outright", "OTHER": "Other"}
PURPOSE_LABELS = {
    "VENTURE": "Business venture",
    "EDUCATION": "Education",
    "PERSONAL": "Personal",
    "MEDICAL": "Medical",
    "HOMEIMPROVEMENT": "Home improvement",
    "DEBTCONSOLIDATION": "Debt consolidation",
}


def group_row(
    label: str,
    scores: np.ndarray,
    raw_pd: np.ndarray,
    calibrated_pd: np.ndarray,
    y: np.ndarray,
) -> dict:
    """Outcomes of one group. Every rate is a share of that group's own loans."""
    rows = int(len(y))
    defaults = int(y.sum())
    good, bad = y == 0, y == 1
    observed = float(y.mean())
    predicted = float(calibrated_pd.mean())
    # Is the gap larger than the group's size alone would produce?
    margin = Z_95 * math.sqrt(max(predicted * (1.0 - predicted), 1e-12) / rows)
    gap = predicted - observed
    return {
        "group": label,
        "rows": rows,
        "defaults": defaults,
        "observed_default_rate": observed,
        "predicted_default_rate": predicted,
        "calibration_gap": gap,
        "gap_margin_95": margin,
        "gap_beyond_noise": bool(abs(gap) > margin),
        "approval_rate": float((scores > MANUAL_REVIEW_UPPER_BOUND).mean()),
        "rejection_rate": float((scores <= REJECT_UPPER_BOUND).mean()),
        # Good payers the model would have turned away.
        "good_payers_rejected": (
            float((scores[good] <= REJECT_UPPER_BOUND).mean()) if good.any() else None
        ),
        # Defaulters the model would have approved outright.
        "defaulters_approved": (
            float((scores[bad] > MANUAL_REVIEW_UPPER_BOUND).mean()) if bad.any() else None
        ),
        "auc_roc": float(roc_auc_score(y, raw_pd)) if 0 < defaults < rows else None,
        "small_group": rows < MIN_GROUP_ROWS,
    }


def audit_attribute(
    name: str,
    note: str,
    labels: pd.Series,
    order: list[str],
    scores: np.ndarray,
    raw_pd: np.ndarray,
    calibrated_pd: np.ndarray,
    y: np.ndarray,
) -> dict:
    """All groups of one attribute, with approval ratios against the best group."""
    values = labels.to_numpy()
    groups = []
    for label in order:
        mask = values == label
        if mask.any():
            groups.append(
                group_row(label, scores[mask], raw_pd[mask], calibrated_pd[mask], y[mask])
            )
    sized = [row for row in groups if not row["small_group"]]
    reference = max(sized, key=lambda row: row["approval_rate"])
    for row in groups:
        row["approval_ratio"] = (
            row["approval_rate"] / reference["approval_rate"]
            if reference["approval_rate"] > 0
            else None
        )
        row["below_four_fifths"] = bool(
            not row["small_group"]
            and row["approval_ratio"] is not None
            and row["approval_ratio"] < FOUR_FIFTHS
        )
    return {
        "attribute": name,
        "note": note,
        "reference_group": reference["group"],
        "groups": groups,
        "largest_gap": max((abs(row["calibration_gap"]) for row in sized), default=0.0),
        "groups_mispriced": [row["group"] for row in sized if row["gap_beyond_noise"]],
        "groups_below_four_fifths": [row["group"] for row in sized if row["below_four_fifths"]],
    }


def main() -> int:
    """Score the hold-out, split it by group and write the JSON."""
    metadata = load_feature_metadata()
    features = metadata["feature_names"]
    evaluation = load_model_evaluation()
    if evaluation is None or evaluation.get("model_trained_at") != metadata.get("trained_at"):
        raise SystemExit("Run `python -m ml.evaluate_model` first: no calibrator for this model.")

    source = load_datasets(("credit_risk",))["credit_risk"]
    mapped = {"credit_risk": map_credit_risk(source)}
    winner = next(c for c in build_candidates(mapped) if c.name == metadata["dataset"])
    X, y = winner.frame[features], winner.frame[TARGET]
    X_train, X_test, _, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE
    )

    model = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
    raw_pd = model.predict_proba(scaler.transform(X_test.to_numpy()))[:, 1]
    calibrator = evaluation["calibrator"]
    calibrated_pd = np.interp(
        raw_pd, calibrator["raw_probability"], calibrator["calibrated_probability"]
    )
    scores = 100.0 * (1.0 - raw_pd)
    y_arr = y_test.to_numpy()

    # The attributes the model never saw, for the same hold-out rows. Income
    # quarters are cut on the training rows so the hold-out does not define them.
    held = source.loc[X_test.index]
    cuts = source.loc[X_train.index, "person_income"].quantile([0.25, 0.5, 0.75]).tolist()
    attributes = [
        (
            "Age",
            "Years in operation is one of the three inputs, and the young have fewer.",
            pd.cut(held["person_age"], AGE_EDGES, labels=AGE_LABELS).astype(str),
            AGE_LABELS,
        ),
        (
            "Income",
            "Facility size against income is the main input, so small earners "
            "borrowing the same amount score lower by design. Cut on annual income "
            f"at {cuts[0]:,.0f} / {cuts[1]:,.0f} / {cuts[2]:,.0f} (file currency).",
            pd.cut(
                held["person_income"], [-1.0, *cuts, float("inf")], labels=INCOME_LABELS
            ).astype(str),
            INCOME_LABELS,
        ),
        (
            "Housing",
            "The model has no input for assets or collateral.",
            held["person_home_ownership"].map(HOME_LABELS).fillna("Other"),
            list(HOME_LABELS.values()),
        ),
        (
            "Loan purpose",
            "The model has no input for what the loan is for.",
            held["loan_intent"].map(PURPOSE_LABELS).fillna("Other"),
            list(PURPOSE_LABELS.values()),
        ),
    ]

    payload = {
        "dataset": metadata["dataset"],
        "model_trained_at": metadata.get("trained_at"),
        "protocol": (
            "The served model on the same 20% hold-out as the evaluation, joined "
            "to attributes of the public file that the model never reads. Approved "
            f"means a score above {MANUAL_REVIEW_UPPER_BOUND:.0f}; rejected means "
            f"{REJECT_UPPER_BOUND:.0f} or below. A group under {MIN_GROUP_ROWS} "
            "loans is shown but takes no part in a verdict."
        ),
        "rows": int(len(y_arr)),
        "overall": group_row("All", scores, raw_pd, calibrated_pd, y_arr),
        "four_fifths": FOUR_FIFTHS,
        "min_group_rows": MIN_GROUP_ROWS,
        "not_audited": [
            "Gender: the file does not record it.",
            "Region, religion and ethnicity: the file does not record them.",
            "Pakistani SMEs: these are consumer loans from a public file.",
        ],
        "attributes": [
            audit_attribute(name, note, labels, order, scores, raw_pd, calibrated_pd, y_arr)
            for name, note, labels, order in attributes
        ],
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    FAIRNESS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    for block in payload["attributes"]:
        print(f"\n{block['attribute']} (reference: {block['reference_group']})")
        for row in block["groups"]:
            print(
                f"  {row['group']:<20} n={row['rows']:>5}  approved {row['approval_rate']:.3f}"
                f"  ratio {row['approval_ratio']:.2f}  observed {row['observed_default_rate']:.3f}"
                f"  predicted {row['predicted_default_rate']:.3f}"
                f"{'  MISPRICED' if row['gap_beyond_noise'] and not row['small_group'] else ''}"
            )
    print(f"\nwrote {FAIRNESS_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
