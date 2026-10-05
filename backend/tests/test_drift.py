"""Population drift: PSI of live applications against the training reference."""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from ml.features import load_model_evaluation
from services.drift_service import drift_report, psi, shares, verdict
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT

REFERENCE = (load_model_evaluation() or {}).get("reference_distributions")
needs_reference = pytest.mark.skipif(REFERENCE is None, reason="ml.evaluate_model not run")


def test_shares_use_lower_edges_and_an_open_last_bin() -> None:
    assert shares([0, 5, 10, 19.9, 20, 500], [0, 10, 20]) == pytest.approx([2 / 6, 2 / 6, 2 / 6])
    assert shares([], [0, 10]) == [0.0, 0.0]


def test_psi_is_zero_for_identical_shares_and_matches_the_formula() -> None:
    assert psi([0.2, 0.8], [0.2, 0.8]) == 0
    expected = (0.5 - 0.2) * math.log(0.5 / 0.2) + (0.5 - 0.8) * math.log(0.5 / 0.8)
    assert psi([0.5, 0.5], [0.2, 0.8]) == pytest.approx(expected)
    assert math.isfinite(psi([1.0, 0.0], [0.5, 0.5]))  # an empty bin does not blow up


def test_verdicts_respect_sample_size_and_noise() -> None:
    assert verdict(0.9, rows=20, noise_floor=0.2) == "too few applications"
    assert verdict(0.05, rows=500, noise_floor=0.01) == "stable"
    assert verdict(0.18, rows=500, noise_floor=0.01) == "watch"
    assert verdict(0.40, rows=500, noise_floor=0.01) == "shifted"
    # 0.18 would be "watch", but with 110 rows chance alone gives about 0.09.
    assert verdict(0.17, rows=110, noise_floor=0.09) == "stable"


def test_report_shape() -> None:
    reference = {"x": {"edges": [0, 1], "labels": ["low", "high"], "shares": [0.5, 0.5]}}
    report = drift_report(reference, {"x": [0.2] * 150 + [1.5] * 150})
    (row,) = report["quantities"]

    assert report["live_applications"] == 300
    assert row["live_shares"] == [0.5, 0.5]
    assert row["psi"] == 0 and row["verdict"] == "stable"
    assert row["noise_floor"] == pytest.approx(1 / 300, abs=1e-4)


@needs_reference
def test_reference_shares_sum_to_one() -> None:
    for spec in REFERENCE.values():
        assert sum(spec["shares"]) == pytest.approx(1.0)
        assert len(spec["shares"]) == len(spec["edges"]) == len(spec["labels"])


@needs_reference
def test_drift_endpoint(client: TestClient) -> None:
    assert client.get("/model/drift", headers={"Authorization": ""}).status_code == 401
    empty = client.get("/model/drift").json()
    assert empty["live_applications"] == 0
    assert all(row["psi"] is None for row in empty["quantities"])

    for payload in (STRONG_APPLICANT, MID_APPLICANT, WEAK_APPLICANT):
        client.post("/score", json=payload)
    body = client.get("/model/drift").json()

    assert body["live_applications"] == 3
    by_name = {row["name"]: row for row in body["quantities"]}
    assert set(by_name) == set(REFERENCE)
    for row in by_name.values():
        assert sum(row["live_shares"]) == pytest.approx(1.0)
        assert row["verdict"] == "too few applications"
    # STRONG is 12 years, MID 4, WEAK 0.5: one applicant in each of three bins.
    assert by_name["years_in_operation"]["live_shares"] == pytest.approx(
        [1 / 3, 0, 1 / 3, 0, 1 / 3]
    )
