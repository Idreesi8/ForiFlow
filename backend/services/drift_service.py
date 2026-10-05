"""Population drift: are live applicants still like the ones the model learned from?

A model is only as good as the match between the people it scores and the
people it was trained on. This module compares the two with the Population
Stability Index (PSI), the measure banks use for exactly this:

    PSI = sum over bins of (live share - reference share) * ln(live / reference)

The usual reading is below 0.10 stable, 0.10 to 0.25 worth watching, above 0.25
a material shift. Those cut-offs are an industry rule of thumb, not a
statistical test, and with few applications PSI is inflated by chance alone:
its expected value with no shift at all is about (bins - 1) / live rows. That
noise floor is reported beside every figure so a small portfolio is not read
as drift.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from typing import Any

WATCH_PSI = 0.10
SHIFT_PSI = 0.25
# Below this many live applications the verdict is withheld.
MIN_ROWS_FOR_VERDICT = 100
# Empty bins would make the logarithm infinite; both shares are floored here.
SHARE_FLOOR = 0.0001

LABELS = {
    "risk_score": "Score",
    "loan_to_income": "Facility size vs annual turnover",
    "payment_history_score": "Repayment history",
    "years_in_operation": "Years in operation",
}


def shares(values: list[float], edges: list[float]) -> list[float]:
    """Share of ``values`` in each bin defined by its lower ``edges``."""
    counts = [0] * len(edges)
    for value in values:
        counts[min(max(bisect_right(edges, value) - 1, 0), len(edges) - 1)] += 1
    return [count / len(values) for count in counts] if values else [0.0] * len(edges)


def psi(live: list[float], reference: list[float]) -> float:
    """Population Stability Index between two sets of bin shares."""
    total = 0.0
    for actual, expected in zip(live, reference, strict=True):
        actual, expected = max(actual, SHARE_FLOOR), max(expected, SHARE_FLOOR)
        total += (actual - expected) * math.log(actual / expected)
    return total


def verdict(value: float, rows: int, noise_floor: float) -> str:
    """Plain reading of one PSI figure."""
    if rows < MIN_ROWS_FOR_VERDICT:
        return "too few applications"
    if value <= max(WATCH_PSI, 2 * noise_floor):
        return "stable"
    return "shifted" if value > SHIFT_PSI else "watch"


def drift_report(
    reference: dict[str, dict[str, Any]], live_values: dict[str, list[float]]
) -> dict[str, Any]:
    """PSI of every monitored quantity against its training reference."""
    rows_out = []
    for name, spec in reference.items():
        values = live_values.get(name, [])
        live = shares(values, spec["edges"])
        value = psi(live, spec["shares"]) if values else None
        noise_floor = (len(spec["edges"]) - 1) / len(values) if values else None
        rows_out.append(
            {
                "name": name,
                "label": LABELS.get(name, name),
                "bins": spec["labels"],
                "reference_shares": spec["shares"],
                "live_shares": live,
                "psi": round(value, 4) if value is not None else None,
                "noise_floor": round(noise_floor, 4) if noise_floor is not None else None,
                "verdict": (
                    verdict(value, len(values), noise_floor)
                    if value is not None
                    else "no applications yet"
                ),
            }
        )
    live_rows = max((len(values) for values in live_values.values()), default=0)
    return {
        "live_applications": live_rows,
        "min_rows_for_verdict": MIN_ROWS_FOR_VERDICT,
        "thresholds": {"watch": WATCH_PSI, "shift": SHIFT_PSI},
        "quantities": rows_out,
    }
