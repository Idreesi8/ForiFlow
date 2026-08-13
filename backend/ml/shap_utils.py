"""Helpers for reading SHAP output consistently in training and serving.

``shap`` returns different array shapes depending on the model family and
version: a binary classifier may yield ``(n_samples, n_features)`` for the
positive class alone, or ``(n_samples, n_features, n_classes)``. Normalising in
one place keeps the training-time additivity check and the request-time
explanation in agreement.
"""

from __future__ import annotations

import numpy as np


def positive_class_shap(values) -> np.ndarray:
    """Return SHAP values for the positive class as ``(n_samples, n_features)``."""
    array = np.asarray(values)
    if array.ndim == 3:
        return array[:, :, -1]
    return array


def expected_positive_value(explainer) -> float:
    """Return an explainer's expected value for the positive class."""
    expected = np.asarray(explainer.expected_value, dtype=float).ravel()
    return float(expected[-1])
