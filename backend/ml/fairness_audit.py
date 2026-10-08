"""Subgroup Performance Analysis of the served model (formerly "group audit").

Since 2.2 this runs inside ``python -m ml.evaluate_model``, on the final test
set, once. It joins each test loan back to four attributes of the public file
that the model never reads (age, income, housing, loan purpose) and reports
per group, where the sample allows:

* sample count, defaults and default rate;
* ROC-AUC, and precision and recall at the model evaluation threshold
  (raw probability 0.5, fixed in advance, not a credit policy threshold);
* the calibrated probability against the observed default rate;
* approval and rejection shares at the demo policy's 40 / 70 cut-offs, which
  describe that policy, not the model.

A group with fewer than :data:`MIN_GROUP_ROWS` loans, or fewer than
:data:`MIN_CLASS_ROWS` defaults or non-defaults, is marked "Insufficient
sample size" and its AUC is not reported. Similar figures across groups do not
make the model "fair": the file is consumer loans, has no gender, region or
religion, and is not Pakistani SME data.
"""

from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from ml.evaluate_model import MANUAL_REVIEW_UPPER_BOUND, REJECT_UPPER_BOUND

# A group smaller than this is reported but takes no part in any verdict.
MIN_GROUP_ROWS = 100
# Below this many defaults (or non-defaults) AUC, precision and recall are noise.
MIN_CLASS_ROWS = 10
INSUFFICIENT = "Insufficient sample size"
# Model evaluation threshold on the raw probability (see ml.pipeline).
EVALUATION_THRESHOLD = 0.5
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
    sufficient = (
        rows >= MIN_GROUP_ROWS and defaults >= MIN_CLASS_ROWS and rows - defaults >= MIN_CLASS_ROWS
    )
    flagged = raw_pd >= EVALUATION_THRESHOLD
    caught = int((flagged & bad).sum())
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
        "auc_roc": float(roc_auc_score(y, raw_pd)) if sufficient else None,
        "recall": float(caught / defaults) if defaults else None,
        "precision": float(caught / flagged.sum()) if flagged.any() else None,
        "evaluation_threshold": EVALUATION_THRESHOLD,
        "sample_status": "Sufficient" if sufficient else INSUFFICIENT,
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


def subgroup_analysis(
    held: pd.DataFrame,
    training_rows: pd.DataFrame,
    raw_pd: np.ndarray,
    calibrated_pd: np.ndarray,
    y: np.ndarray,
    *,
    dataset: str,
    trained_at: str | None,
) -> dict:
    """The analysis over ``held`` (the final test rows of the raw file).

    Income quarters are cut on ``training_rows`` so the test set defines nothing.
    """
    scores = 100.0 * (1.0 - raw_pd)
    cuts = training_rows["person_income"].quantile([0.25, 0.5, 0.75]).tolist()
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
            "borrowing the same amount score lower by design. Cut on the training "
            f"split's annual income at {cuts[0]:,.0f} / {cuts[1]:,.0f} / {cuts[2]:,.0f} "
            "(file currency).",
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
    return {
        "title": "Subgroup Performance Analysis",
        "dataset": dataset,
        "model_trained_at": trained_at,
        "evaluated_on": "final test set",
        "protocol": (
            "The served model on the final test set, joined to attributes of the public "
            "file that the model never reads. Precision and recall use the model "
            f"evaluation threshold (raw probability {EVALUATION_THRESHOLD}). Approved and "
            f"rejected use the demo policy cut-offs ({MANUAL_REVIEW_UPPER_BOUND:.0f} / "
            f"{REJECT_UPPER_BOUND:.0f}) and describe that policy, not the model. A group "
            f"under {MIN_GROUP_ROWS} loans, or with under {MIN_CLASS_ROWS} defaults or "
            "non-defaults, is marked insufficient and takes no part in a verdict."
        ),
        "interpretation": (
            "Descriptive only. Similar figures do not establish that the model is fair; "
            "the file is consumer loans without gender, region or religion, not "
            "Pakistani SME lending data."
        ),
        "rows": int(len(y)),
        "overall": group_row("All", scores, raw_pd, calibrated_pd, y),
        "four_fifths": FOUR_FIFTHS,
        "min_group_rows": MIN_GROUP_ROWS,
        "min_class_rows": MIN_CLASS_ROWS,
        "not_audited": [
            "Gender: the file does not record it.",
            "Region, religion and ethnicity: the file does not record them.",
            "Pakistani SMEs: these are consumer loans from a public file.",
        ],
        "attributes": [
            audit_attribute(name, note, labels, order, scores, raw_pd, calibrated_pd, y)
            for name, note, labels, order in attributes
        ],
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def main() -> int:
    """Since 2.2 the analysis is part of the one final evaluation."""
    print("Run `python -m ml.evaluate_model`: it writes the subgroup analysis on the final test set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
