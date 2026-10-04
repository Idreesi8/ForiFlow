"""Fit the early-warning Markov chain on real monthly repayment histories.

Run from the ``backend`` directory::

    python -m ml.ews_markov

ForiFlow's own training files hold one row per loan, so they cannot say how a
borrower moves from month to month. This script uses the UCI "Default of Credit
Card Clients" file (Yeh, 2009; CC BY 4.0; 30,000 clients in Taiwan), which
records the repayment status of each client for six consecutive months, April
to September 2005, plus whether the client defaulted in October.

It estimates how often a borrower moves between repayment states from one
month to the next, checks those estimates on clients it did not see, and
writes ``ml/ews_transition.json`` for the monitoring service. Download the data
from https://archive.ics.uci.edu/dataset/350 and place it in ``ml/data`` as
``uci_credit_card.csv.gz`` (the workbook saved as CSV; ``.zip`` and ``.xls`` are
read too, given ``xlrd``).

What this is not: Pakistani SME repayment data. The chain describes how
consumer card accounts in Taiwan rolled between delinquency buckets in 2005. A
bank would refit it on its own monthly records with this same script.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from ml.features import EWS_TRANSITION_PATH, ML_DIR

DATA_PATH = ML_DIR / "data" / "uci_credit_card.csv.gz"
RANDOM_STATE = 42
HOLDOUT_SHARE = 0.2
# Horizon for the outlook the service reports, and bootstrap size for the
# model comparison.
OUTLOOK_MONTHS = 12
BOOTSTRAP_SAMPLES = 500

# Repayment status columns, oldest month first (April ... September 2005).
PAY_COLUMNS = ("PAY_6", "PAY_5", "PAY_4", "PAY_3", "PAY_2", "PAY_0")
LABEL_COLUMN = "default payment next month"

# Chain states. The file counts delay in whole months; a delay of N months is N
# missed payments, which puts 4 or more at 90+ days past due, the usual default
# line. Months before September almost never record a one-month delay (it is
# folded into the neighbouring values), so one and two months share a state.
STATES = ("Current", "Late 1-59", "Late 60-89", "Default")
DEFAULT = len(STATES) - 1


def state_of(delay: int) -> int:
    """Map the file's months-of-delay code onto a chain state."""
    if delay <= 0:
        return 0  # -2 no balance, -1 paid in full, 0 minimum paid
    if delay <= 2:
        return 1
    if delay == 3:
        return 2
    return DEFAULT


def load_frame(path: Path = DATA_PATH) -> pd.DataFrame:
    """Read the UCI file as shipped (.zip / .xls) or as the extracted CSV."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            name = next(n for n in archive.namelist() if n.lower().endswith((".xls", ".xlsx")))
            return pd.read_excel(io.BytesIO(archive.read(name)), header=1)
    if path.suffix in (".xls", ".xlsx"):
        return pd.read_excel(path, header=1)
    return pd.read_csv(path)


def histories(frame: pd.DataFrame) -> np.ndarray:
    """Per-client chain state for the six months, oldest first.

    Default is absorbing: once an account reaches it, later months stay there,
    which is how a lender treats a facility that has been classified.
    """
    states = frame[list(PAY_COLUMNS)].astype(int).map(state_of).to_numpy()
    reached = np.maximum.accumulate(states == DEFAULT, axis=1)
    return np.where(reached, DEFAULT, states)


def count_transitions(states: np.ndarray) -> np.ndarray:
    """How many month-to-month moves went from each state to each state."""
    counts = np.zeros((len(STATES), len(STATES)), dtype=int)
    np.add.at(counts, (states[:, :-1].ravel(), states[:, 1:].ravel()), 1)
    counts[DEFAULT] = 0
    return counts


def transition_matrix(counts: np.ndarray) -> np.ndarray:
    """Maximum-likelihood transition probabilities; Default is absorbing."""
    matrix = np.zeros(counts.shape, dtype=float)
    for row in range(DEFAULT):
        total = counts[row].sum()
        if total == 0:
            raise ValueError(f"No observed month starts in state {STATES[row]!r}.")
        matrix[row] = counts[row] / total
    matrix[DEFAULT, DEFAULT] = 1.0
    return matrix


def default_by_month(matrix: np.ndarray, state: int, months: int) -> list[float]:
    """Probability of having reached Default within 1..``months`` months."""
    row = np.zeros(len(matrix))
    row[state] = 1.0
    reached = []
    for _ in range(months):
        row = row @ matrix
        reached.append(float(row[DEFAULT]))
    return reached


def expected_days_to_default(matrix: np.ndarray, state: int, months: int) -> float | None:
    """Mean time to Default, given that it happens within ``months`` months.

    The unconditional mean is not used: with Default as the only absorbing
    state it would assume every facility defaults eventually.
    """
    if state == DEFAULT:
        return 0.0
    reached = [0.0, *default_by_month(matrix, state, months)]
    first_passage = np.diff(reached)
    if first_passage.sum() <= 0:
        return None
    month_numbers = np.arange(1, months + 1)
    return float(30.0 * (month_numbers * first_passage).sum() / first_passage.sum())


def second_order_table(states: np.ndarray) -> list[dict]:
    """Does last month matter once this month is known? (The Markov assumption.)"""
    rows = []
    previous, current, following = states[:, :-2], states[:, 1:-1], states[:, 2:]
    for now in range(1, DEFAULT):
        for before in range(DEFAULT):
            mask = (previous == before) & (current == now)
            if mask.sum() == 0:
                continue
            after = following[mask]
            rows.append(
                {
                    "previous": STATES[before],
                    "current": STATES[now],
                    "months": int(mask.sum()),
                    "back_to_current": float((after == 0).mean()),
                    "worse": float((after > now).mean()),
                }
            )
    return rows


def holdout_check(matrix: np.ndarray, states: np.ndarray) -> list[dict]:
    """Predicted against actual Default within five months, by starting state."""
    horizon = states.shape[1] - 1
    rows = []
    for start in range(DEFAULT):
        mask = states[:, 0] == start
        if mask.sum() == 0:
            continue
        rows.append(
            {
                "april_state": STATES[start],
                "clients": int(mask.sum()),
                "predicted_default": default_by_month(matrix, start, horizon)[-1],
                "actual_default": float((states[mask, -1] == DEFAULT).mean()),
            }
        )
    return rows


def october_default_rate(states: np.ndarray, label: np.ndarray) -> list[dict]:
    """The file's own October default flag, by September state."""
    return [
        {
            "september_state": STATES[state],
            "clients": int((states[:, -1] == state).sum()),
            "october_default_rate": float(label[states[:, -1] == state].mean()),
        }
        for state in range(len(STATES))
        if (states[:, -1] == state).any()
    ]


def state_outlook(matrix: np.ndarray) -> list[dict]:
    """What the monitoring service reports for a facility in each state."""
    rows = []
    for state, name in enumerate(STATES):
        reached = default_by_month(matrix, state, OUTLOOK_MONTHS)
        days = expected_days_to_default(matrix, state, OUTLOOK_MONTHS)
        rows.append(
            {
                "state": name,
                "default_within_3_months": 1.0 if state == DEFAULT else reached[2],
                "default_within_12_months": 1.0 if state == DEFAULT else reached[-1],
                "expected_days_to_default": None if days is None else round(days),
            }
        )
    return rows


def compare_alternatives(
    states: np.ndarray, frame: pd.DataFrame, train: np.ndarray, holdout: np.ndarray
) -> dict:
    """Could a richer model predict Default within three months better?

    Every model sees the same client-months (May and June, so the previous
    month is known and three months ahead are observed) and is scored on
    hold-out clients only. The chain uses the repayment state alone; the two
    hazard models also use the previous state, card utilisation and how much of
    the bill was paid. Those extra inputs have no clean counterpart on a term
    loan, which is why they are measured here but not served.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score

    raw = frame[list(PAY_COLUMNS)].to_numpy()
    bill = frame[[f"BILL_AMT{i}" for i in (6, 5, 4, 3, 2, 1)]].to_numpy(dtype=float)
    paid = frame[[f"PAY_AMT{i}" for i in (6, 5, 4, 3, 2, 1)]].to_numpy(dtype=float)
    limit = frame["LIMIT_BAL"].to_numpy(dtype=float)

    def windows(clients: np.ndarray) -> pd.DataFrame:
        parts = []
        for month in (1, 2):
            rows = clients[states[clients, month] != DEFAULT]
            parts.append(
                pd.DataFrame(
                    {
                        "state": states[rows, month],
                        "previous_state": states[rows, month - 1],
                        "delay": raw[rows, month],
                        "previous_delay": raw[rows, month - 1],
                        "utilisation": np.clip(bill[rows, month] / limit[rows], -1, 3),
                        "paid_share": np.clip(
                            paid[rows, month] / np.maximum(bill[rows, month], 1), 0, 2
                        ),
                        "defaulted": (states[rows, month + 3] == DEFAULT).astype(int),
                    }
                )
            )
        return pd.concat(parts, ignore_index=True)

    fit, test = windows(train), windows(holdout)
    y = test["defaulted"].to_numpy()
    matrix = transition_matrix(count_transitions(states[train]))
    by_state = np.array([default_by_month(matrix, s, 3)[-1] for s in range(DEFAULT)])

    pairs = fit.groupby(["previous_state", "state"])["defaulted"].agg(["mean", "size"])

    def second_order(previous: int, state: int) -> float:
        key = (previous, state)
        if key in pairs.index and pairs.loc[key, "size"] >= 50:
            return float(pairs.loc[key, "mean"])
        return float(by_state[state])

    features = ["delay", "previous_delay", "utilisation", "paid_share"]
    logistic = LogisticRegression(max_iter=2000).fit(fit[features], fit["defaulted"])
    boosting = HistGradientBoostingClassifier(
        max_depth=3, learning_rate=0.05, max_iter=200, random_state=RANDOM_STATE
    ).fit(fit[features], fit["defaulted"])

    predictions = {
        "markov_first_order": by_state[test["state"].to_numpy()],
        "markov_second_order": np.array(
            [second_order(a, b) for a, b in zip(test["previous_state"], test["state"])]
        ),
        "logistic_hazard": logistic.predict_proba(test[features])[:, 1],
        "gradient_boosting_hazard": boosting.predict_proba(test[features])[:, 1],
    }

    # With few defaults the AUC is noisy, so the gap to the served chain gets a
    # bootstrap interval over hold-out client-months.
    rng = np.random.default_rng(RANDOM_STATE)
    samples = [rng.integers(0, len(y), len(y)) for _ in range(BOOTSTRAP_SAMPLES)]
    samples = [index for index in samples if 0 < y[index].sum() < len(index)]
    base = predictions["markov_first_order"]

    results = {}
    for name, predicted in predictions.items():
        gaps = [
            roc_auc_score(y[index], predicted[index]) - roc_auc_score(y[index], base[index])
            for index in samples
        ]
        results[name] = {
            "auc_roc": float(roc_auc_score(y, predicted)),
            "brier": float(brier_score_loss(y, predicted)),
            "mean_predicted": float(predicted.mean()),
            "auc_gap_to_served_95": [
                float(np.percentile(gaps, 2.5)),
                float(np.percentile(gaps, 97.5)),
            ],
        }
    return {
        "target": "Default within 3 months",
        "holdout_client_months": int(len(y)),
        "holdout_defaults": int(y.sum()),
        "observed_rate": float(y.mean()),
        "features_of_hazard_models": features,
        "models": results,
    }


def main() -> int:
    """Fit on 80% of clients, check on the other 20%, write the JSON."""
    if not DATA_PATH.exists():
        print(f"Missing {DATA_PATH}. See the module docstring for where to get it.")
        return 1
    frame = load_frame()
    states = histories(frame)
    label = frame[LABEL_COLUMN].astype(int).to_numpy()

    order = np.random.default_rng(RANDOM_STATE).permutation(len(states))
    cut = int(len(states) * (1 - HOLDOUT_SHARE))
    train_clients, holdout_clients = order[:cut], order[cut:]
    train, holdout = states[train_clients], states[holdout_clients]

    counts = count_transitions(train)
    matrix = transition_matrix(counts)

    payload = {
        "source": (
            "UCI Default of Credit Card Clients (Yeh, 2009), CC BY 4.0. Consumer "
            "card accounts in Taiwan, April to September 2005. Not SME loans."
        ),
        "states": list(STATES),
        "state_definition": (
            "Months of delay in the file: 0 or less = Current, 1-2 = Late 1-59, "
            "3 = Late 60-89, 4 or more = Default (absorbing)."
        ),
        "clients": {"train": int(len(train)), "holdout": int(len(holdout))},
        "transition_counts": counts.tolist(),
        "transition_matrix": [[float(v) for v in row] for row in matrix],
        "state_outlook": state_outlook(matrix),
        "outlook_months": OUTLOOK_MONTHS,
        "holdout_check": holdout_check(matrix, holdout),
        "alternatives": compare_alternatives(states, frame, train_clients, holdout_clients),
        "markov_assumption": second_order_table(train),
        "october_default_by_state": october_default_rate(states, label),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    EWS_TRANSITION_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"{len(train):,} training clients, {len(holdout):,} hold-out clients\n")
    print(f"{'from / to':<12}" + "".join(f"{name:>12}" for name in STATES) + f"{'months':>10}")
    for name, row, row_counts in zip(STATES, matrix, counts, strict=True):
        print(f"{name:<12}" + "".join(f"{v:>12.4f}" for v in row) + f"{row_counts.sum():>10,}")
    print()
    for row in payload["holdout_check"]:
        print(
            f"  from {row['april_state']:<11} n={row['clients']:>5}  default within 5 months: "
            f"predicted {row['predicted_default']:.4f}  actual {row['actual_default']:.4f}"
        )
    print()
    for name, row in payload["alternatives"]["models"].items():
        low, high = row["auc_gap_to_served_95"]
        print(
            f"  {name:<26} AUC {row['auc_roc']:.4f}  Brier {row['brier']:.5f}  "
            f"gap to served [{low:+.4f}, {high:+.4f}]"
        )
    print(f"\nwrote {EWS_TRANSITION_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
