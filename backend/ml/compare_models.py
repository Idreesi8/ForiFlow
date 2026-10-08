"""Baseline comparison (superseded entry point).

Since 2.2 the comparison of the served ensemble with logistic regression,
XGBoost alone and random forest alone is part of the training protocol
(:mod:`ml.pipeline`): every model gets the same split, the same train-only
preprocessing and SMOTE, 5-fold CV on the training split and validation
metrics (``ml.train_real_model``), then final-test metrics once
(``ml.evaluate_model``). Both write ``ml/model_comparison.json``.

The pre-2.2 version of this script cross-validated on a frame whose medians and
clip bounds had been learned on the whole file, so it is not kept.
"""

from __future__ import annotations


def main() -> int:
    print(
        "Run `python -m ml.train_real_model` then `python -m ml.evaluate_model`: "
        "they write ml/model_comparison.json under the 2.2 protocol."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
