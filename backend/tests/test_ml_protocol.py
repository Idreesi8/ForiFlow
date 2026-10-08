"""The 2.2 ML protocol: no leakage, an untouched final test set, honest records.

The protocol tests run on small synthetic data, so they need neither the
public file nor the trained artefacts. The record tests read the committed
artefacts and skip when they are absent.
"""

from __future__ import annotations

import copy
import json
import re

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from main import app
from ml import pipeline
from ml.data_quality import DATA_QUALITY_PATH, data_quality_report, load_data_quality
from ml.evaluate_model import AlreadyEvaluated, SplitMismatch, check_split, guard_single_use
from ml.fairness_audit import INSUFFICIENT, MIN_GROUP_ROWS, group_row
from ml.features import (
    COMPARISON_PATH,
    DATA_DIR,
    load_feature_metadata,
    load_model_comparison,
    load_model_evaluation,
)
from models.database import Application, ModelVersion
from schemas import SMEApplicant
from services.scoring_service import MLScoringService, ScoringService, get_scoring_service
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT

FEATURES = list(pipeline.MODEL_FEATURES)


def _metadata() -> dict | None:
    try:
        return load_feature_metadata()
    except (OSError, ValueError):
        return None


METADATA = _metadata()
EVALUATION = load_model_evaluation()
is_22 = pytest.mark.skipif(
    not METADATA or "training_protocol_version" not in METADATA,
    reason="artefacts not trained under the 2.2 protocol",
)
evaluated = pytest.mark.skipif(
    not EVALUATION or EVALUATION.get("model_trained_at") != (METADATA or {}).get("trained_at")
    or "final_test" not in EVALUATION,
    reason="no final-test evaluation for these artefacts",
)
has_data = pytest.mark.skipif(
    not (DATA_DIR / pipeline.DATASET_FILE).exists(), reason="training file not present"
)


def synthetic(rows: int = 600, seed: int = 0) -> pd.DataFrame:
    """A small frame shaped like the modelling frame, with a real signal."""
    rng = np.random.default_rng(seed)
    lti = rng.uniform(0.02, 0.6, rows)
    history = rng.choice([25.0, 80.0], rows, p=[0.2, 0.8])
    years = rng.integers(0, 15, rows).astype(float)
    risk = 1 / (1 + np.exp(-(-1.5 + 4 * lti - 0.02 * (history - 50) - 0.05 * years)))
    frame = pd.DataFrame(
        {
            "loan_to_income": lti,
            "payment_history_score": history,
            "years_in_operation": years,
            pipeline.TARGET: (rng.uniform(size=rows) < risk).astype(int),
        }
    )
    frame.loc[rng.choice(rows, 30, replace=False), "years_in_operation"] = np.nan
    frame.index.name = "row_id"
    return frame


# --- A. preprocessing is learned on training rows only -----------------------------


def test_preprocessing_parameters_come_from_the_training_rows_only() -> None:
    frame = synthetic()
    split = pipeline.split_rows(frame)
    train = frame.loc[split.train, FEATURES]
    test = frame.loc[split.test, FEATURES].copy()
    # Poison the test rows: extremes and gaps that would move a whole-file statistic.
    test.iloc[:20, 0] = 1_000.0
    test.iloc[20:40, 2] = np.nan

    fitted = pipeline.TrainOnlyPreprocessor().fit(train)
    reference = pipeline.TrainOnlyPreprocessor().fit(train.copy())
    assert fitted.clips_ == reference.clips_
    assert fitted.medians_ == {c: float(train[c].median()) for c in FEATURES}
    assert fitted.n_fit_rows_ == len(train)

    out = fitted.transform(test)
    assert out[:20, 0].max() == pytest.approx(fitted.clips_["loan_to_income"][1])
    assert np.all(out[20:40, 2] == pytest.approx(fitted.medians_["years_in_operation"]))
    # A whole-file fit would have learned a different upper bound.
    whole = pipeline.TrainOnlyPreprocessor().fit(pd.concat([train, test]))
    assert whole.clips_["loan_to_income"][1] != fitted.clips_["loan_to_income"][1]


def test_each_cv_fold_refits_preprocessing_on_its_own_training_part(monkeypatch) -> None:
    frame = synthetic(400)
    seen: list[int] = []
    original = pipeline.TrainOnlyPreprocessor.fit

    def spy(self, X, y=None):
        seen.append(len(X))
        return original(self, X, y)

    monkeypatch.setattr(pipeline.TrainOnlyPreprocessor, "fit", spy)
    pipeline.cross_validate_training("logistic_regression", frame[FEATURES], frame[pipeline.TARGET], folds=4)
    assert seen == [300, 300, 300, 300]  # never the whole 400


# --- B. split isolation --------------------------------------------------------------


def test_the_split_is_disjoint_complete_stratified_and_reproducible() -> None:
    frame = synthetic(1_000)
    split = pipeline.split_rows(frame, seed=42)
    sets = [set(split.train), set(split.validation), set(split.test)]
    assert not (sets[0] & sets[1]) and not (sets[0] & sets[2]) and not (sets[1] & sets[2])
    assert set().union(*sets) == set(frame.index)
    assert (len(split.train), len(split.validation), len(split.test)) == (600, 200, 200)
    rates = split.describe(frame)["default_rate"]
    overall = frame[pipeline.TARGET].mean()
    assert all(abs(rate - overall) < 0.02 for rate in rates.values())

    again = pipeline.split_rows(frame, seed=42)
    assert again.describe(frame)["id_sha256"] == split.describe(frame)["id_sha256"]
    other = pipeline.split_rows(frame, seed=7)
    assert other.describe(frame)["id_sha256"]["final_test"] != split.describe(frame)["id_sha256"]["final_test"]


def test_exact_duplicate_rows_are_dropped_before_the_split() -> None:
    raw = pd.DataFrame(
        {
            "person_income": [50_000, 50_000, 40_000],
            "loan_amnt": [5_000, 5_000, 2_000],
            "cb_person_default_on_file": ["N", "N", "Y"],
            "person_emp_length": [3.0, 3.0, np.nan],
            "loan_status": [0, 0, 1],
        }
    )
    prepared = pipeline.prepare_frame(raw)
    assert prepared.excluded == {"exact_duplicate_rows": 1}
    assert list(prepared.frame.index) == [0, 2]
    # Missing values are left for the training split to impute.
    assert np.isnan(prepared.frame.loc[2, "years_in_operation"])


# --- C. SMOTE touches training rows only ------------------------------------------


def test_smote_runs_on_fit_and_never_on_scoring(monkeypatch) -> None:
    from imblearn.over_sampling import SMOTE

    frame = synthetic(500)
    split = pipeline.split_rows(frame)
    calls: list[int] = []
    original = SMOTE.fit_resample

    def spy(self, X, y):
        calls.append(len(X))
        return original(self, X, y)

    monkeypatch.setattr(SMOTE, "fit_resample", spy)
    fitted = pipeline.build_training_pipeline("logistic_regression", FEATURES)
    fitted.fit(frame.loc[split.train, FEATURES], frame.loc[split.train, pipeline.TARGET])
    assert calls == [len(split.train)]

    probability = fitted.predict_proba(frame.loc[split.test, FEATURES])
    assert calls == [len(split.train)]  # scoring resampled nothing
    assert probability.shape == (len(split.test), 2)


# --- D. the final test set is used once -------------------------------------------


def test_the_final_evaluation_refuses_a_second_run() -> None:
    metadata = {"trained_at": "2026-10-08T12:00:00"}
    done = {"model_trained_at": "2026-10-08T12:00:00", "final_test": {"rows": 10}, "recorded_at": "x"}
    with pytest.raises(AlreadyEvaluated):
        guard_single_use(metadata, done, force=False)
    guard_single_use(metadata, done, force=True)  # explicit, and reported as such
    guard_single_use(metadata, {**done, "model_trained_at": "older"}, force=False)
    guard_single_use(metadata, None, force=False)


def test_the_final_evaluation_refuses_a_different_split() -> None:
    frame = synthetic(300)
    info = pipeline.split_rows(frame).describe(frame)
    check_split(info, {"split": {"id_sha256": info["id_sha256"]}})
    with pytest.raises(SplitMismatch):
        check_split(info, {"split": {"id_sha256": {**info["id_sha256"], "final_test": "0" * 64}}})
    with pytest.raises(SplitMismatch):
        check_split(info, {})


@is_22
def test_the_recorded_split_and_its_uses() -> None:
    split = METADATA["split"]
    rows = split["rows"]
    assert rows["train"] + rows["validation"] + rows["final_test"] == METADATA["rows"]
    assert split["seed"] == METADATA["random_seed"] == 42
    assert len(set(split["id_sha256"].values())) == 3
    assert "nothing is chosen or tuned" in split["uses"]["final_test"]
    assert METADATA["calibration"]["fitted_on"] == {"set": "validation", "rows": rows["validation"]}
    assert METADATA["validation"]["rows"] == rows["validation"]
    assert METADATA["cross_validation"]["scope"] == "training split only"


@is_22
@has_data
def test_the_recorded_split_is_rebuilt_from_the_file_and_seed() -> None:
    prepared = pipeline.load_prepared()
    assert prepared.dataset_sha256 == METADATA["dataset_sha256"]
    rebuilt = pipeline.split_rows(prepared.frame, seed=METADATA["random_seed"]).describe(prepared.frame)
    assert rebuilt["id_sha256"] == METADATA["split"]["id_sha256"]
    assert prepared.excluded == METADATA["excluded_rows"]


# --- E. calibration is fitted on validation rows only -----------------------------


def test_calibration_is_chosen_by_cross_fitting_and_fitted_on_what_it_is_given() -> None:
    rng = np.random.default_rng(1)
    true_pd = rng.uniform(0.02, 0.6, 3_000)
    y = (rng.uniform(size=true_pd.size) < true_pd).astype(int)
    raw = 0.35 + 0.6 * true_pd  # ranks right, levels wrong (a SMOTE-like prior)

    result = pipeline.select_calibration(raw, y)
    briers = result["selection"]["brier_out_of_fold"]
    assert result["method"] in ("isotonic", "sigmoid")
    assert briers[result["method"]] < briers["none"]
    assert result["fitted_on"]["rows"] == 3_000
    assert result["display_only"] is True
    points = result["calibrated_probability"]
    assert points == sorted(points)  # monotone: never reorders applicants
    assert abs(pipeline.apply_breakpoints(raw, result["raw_probability"], points).mean() - y.mean()) < 0.02


@is_22
@evaluated
def test_calibration_helps_on_the_final_test_set_without_costing_ranking() -> None:
    final = EVALUATION["final_test"]
    assert final["calibrated"]["brier"] < final["brier_no_skill"] < final["raw"]["brier"]
    assert abs(final["raw"]["auc_roc"] - final["calibrated"]["auc_roc"]) < 0.005
    assert EVALUATION["calibrator"]["raw_probability"] == METADATA["calibration"]["raw_probability"]


# --- F. baselines under the same protocol -----------------------------------------


@is_22
@evaluated
def test_baselines_are_compared_honestly() -> None:
    baselines = EVALUATION["baselines"]
    assert set(baselines) == set(pipeline.MODEL_NAMES)
    for name, row in baselines.items():
        assert row["reproduced"] is True, name  # refitted baselines match training
        for key in ("auc_roc", "pr_auc", "f1", "brier", "precision", "recall"):
            assert 0.0 <= row["final_test"][key] <= 1.0
    comparison = load_model_comparison()
    assert comparison["model_trained_at"] == METADATA["trained_at"]
    for key in ("logistic_regression", "xgboost", "random_forest", "served_ensemble_xgb_rf"):
        model = comparison["models"][key]
        assert {"cross_validation", "validation", "final_test"} <= set(model)
    assert baselines["ensemble"]["auc_gap_to_ensemble"] == 0.0


# --- G. SHAP additivity, strictly ---------------------------------------------------


@pytest.mark.ml
def test_shap_reproduces_every_member_and_the_ensemble_exactly(ml_service) -> None:
    """Unrounded probability-space attributions add up to 1e-6, ties included.

    0.5 years in operation sits exactly on a split threshold (the midpoint of
    whole years in training); it is in the grid on purpose.
    """
    from ml.shap_utils import expected_positive_value

    grid = [
        {**WEAK_APPLICANT, "years_in_operation": years, "payment_history_score": history,
         "loan_amount_pkr": amount}
        for years in (0.0, 0.5, 1.5, 4.0, 18.0, 40.0)
        for history in (10, 80)
        for amount in (100_000, 900_000, 9_000_000)
    ] + [STRONG_APPLICANT, MID_APPLICANT, WEAK_APPLICANT]
    for payload in grid:
        applicant = SMEApplicant(**payload)
        scaled, _, _ = ml_service._feature_frame(applicant)
        member_pds = ml_service._member_probabilities(scaled)
        total = 0.0
        for name, explainer in ml_service.explainers.items():
            values = ml_service._member_shap(name, explainer, scaled, member_pds[name])
            member_total = expected_positive_value(explainer) + values.sum()
            assert member_total == pytest.approx(member_pds[name], abs=1e-6), (name, payload)
            total += ml_service.shap_weights[name] * member_total
        assert total == pytest.approx(ml_service._ensemble_probability(member_pds), abs=1e-6)
        result = ml_service.score(applicant)
        # Rounded to 2 decimals per value: at most a few hundredths apart.
        assert ml_service.base_value + sum(result.contributions.values()) == pytest.approx(
            result.risk_score, abs=0.02
        )


# --- H/I/J. dataset and model metadata ----------------------------------------------


@is_22
def test_the_metadata_identifies_data_model_and_protocol() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", METADATA["dataset_sha256"])
    assert METADATA["dataset_type"] == "public_consumer_credit"
    assert "not Pakistani SME" in METADATA["dataset_type_label"]
    assert METADATA["feature_names"] == FEATURES
    assert METADATA["preprocessing"]["version"] == "2.2.0"
    assert METADATA["preprocessing"]["fitted_on"] == "training split only"
    assert set(METADATA["feature_clips"]) == set(FEATURES) == set(METADATA["feature_medians"])
    assert {"xgboost", "random_forest", "smote"} <= set(METADATA["model_config"])
    assert METADATA["calibration"]["method"] in ("isotonic", "sigmoid", None)
    assert METADATA["training_protocol_version"] == "2.2.0"
    assert METADATA["shap_additivity_max_error"] < 1e-6
    assert "not the average of a bank portfolio" in METADATA["shap_reference"]["description"]
    assert METADATA["previous_model"]["holdout_auc_roc"] is not None  # the before figures


@has_data
@is_22
def test_the_dataset_hash_is_the_file_s_hash() -> None:
    assert pipeline.file_sha256(DATA_DIR / pipeline.DATASET_FILE) == METADATA["dataset_sha256"]


@pytest.mark.ml
def test_the_model_version_follows_the_training_run(ml_service) -> None:
    assert ml_service.model_version.endswith(ml_service.metadata["trained_at"])
    changed = copy.deepcopy(ml_service.metadata)
    changed["trained_at"] = "1999-01-01T00:00:00"
    other = MLScoringService(
        ml_service.model, ml_service.scaler,
        {"explainers": ml_service.explainers, "weights": ml_service.shap_weights,
         "output_space": ml_service.output_space},
        changed,
    )
    assert other.model_version != ml_service.model_version
    assert other.artifact_sha256 != ml_service.artifact_sha256


# --- K/L/M. history survives a new model ------------------------------------------


@pytest.mark.ml
def test_a_new_model_leaves_old_versions_scores_and_policy_snapshots_alone(
    ml_client: TestClient, ml_service, db_session_factory
) -> None:
    # A stand-in for the 2.1 model: same trees, 2.1-style metadata, its own version.
    legacy_metadata = {
        key: value
        for key, value in copy.deepcopy(ml_service.metadata).items()
        if key not in ("training_protocol_version", "calibration", "validation", "split")
    }
    legacy_metadata["trained_at"] = "2026-09-25T10:38:26"
    legacy_metadata["holdout"] = {"auc": 0.7731, "f1": 0.5464, "pr_auc": 0.5645, "brier": 0.1852}
    legacy = MLScoringService(
        ml_service.model, ml_service.scaler,
        {"explainers": ml_service.explainers, "weights": ml_service.shap_weights,
         "output_space": ml_service.output_space},
        legacy_metadata,
    )
    app.dependency_overrides[get_scoring_service] = lambda: legacy
    old = ml_client.post("/score", json=MID_APPLICANT).json()
    app.dependency_overrides[get_scoring_service] = lambda: ml_service
    new = ml_client.post("/score", json=STRONG_APPLICANT).json()

    db = db_session_factory()
    try:
        old_row = db.get(Application, old["application_id"])
        versions = {row.version: row for row in db.scalars(select(ModelVersion))}
    finally:
        db.close()
    assert old_row.model_version == legacy.model_version != ml_service.model_version
    assert old_row.risk_score == old["risk_score"]
    snapshot = copy.deepcopy(old_row.policy_evaluation)
    assert snapshot  # the policy snapshot written when it was scored
    stored = ml_client.get(f"/score/applications/{old['application_id']}").json()
    assert stored["risk_score"] == old["risk_score"]
    assert stored["model_version"] == legacy.model_version
    assert stored["policy"] == old["policy"]
    explained = ml_client.get(f"/explain/{old['application_id']}").json()
    assert explained["base_value"] == old["explanation"]["base_value"]
    assert explained["model_version"] == legacy.model_version
    db = db_session_factory()
    try:
        assert db.get(Application, old["application_id"]).policy_evaluation == snapshot
    finally:
        db.close()

    legacy_row = versions[legacy.model_version]
    assert legacy_row.status == "retired"
    assert legacy_row.metrics["holdout_auc_roc"] == 0.7731
    assert legacy_row.provenance is None  # not invented for an older model
    current = versions[ml_service.model_version]
    assert current.status == "active" and current.provenance is not None
    assert new["model_version"] == ml_service.model_version


# --- N. feature contract --------------------------------------------------------------


@pytest.mark.ml
def test_the_feature_contract_names_what_the_trained_model_ignores(ml_client: TestClient) -> None:
    body = ml_client.get("/model/feature-contract").json()
    assert body["engine"] == "ml"
    assert [f["name"] for f in body["model_features"]] == FEATURES
    assert {f["name"] for f in body["collected_unused"]} == {
        "tenure_months", "inventory_turnover", "order_consistency", "existing_debt_pkr", "num_employees",
    }
    assert set(body["used_intake_fields"]) == {
        "loan_amount_pkr", "monthly_digital_payments", "cash_flow_proxy",
        "payment_history_score", "years_in_operation",
    }
    assert body["future_sme_features"] and "None of these" in body["future_note"]


def test_the_fallback_formula_uses_every_scoring_field(client: TestClient) -> None:
    body = client.get("/model/feature-contract").json()
    assert body["engine"] == "surrogate"
    assert body["collected_unused"] == []


@pytest.mark.ml
def test_an_unused_field_does_not_move_the_score(ml_service) -> None:
    base = SMEApplicant(**MID_APPLICANT)
    for field, value in (("inventory_turnover", 49.0), ("order_consistency", 0),
                         ("existing_debt_pkr", 900_000_000), ("num_employees", 4_000),
                         ("tenure_months", 84)):
        changed = SMEApplicant(**{**MID_APPLICANT, field: value})
        assert ml_service.score(changed).risk_score == ml_service.score(base).risk_score, field


# --- O. data quality ---------------------------------------------------------------


def test_the_data_quality_report_counts_what_matters() -> None:
    raw = pd.DataFrame(
        {
            "person_age": [25, 144, 30, 30, None],
            "person_emp_length": [2.0, 123.0, None, None, 1.0],
            "loan_status": [0, 1, 0, 0, 1],
        }
    )
    raw.loc[3] = raw.loc[2]
    report = data_quality_report(
        raw, "loan_status", dataset_identifier="x", dataset_type_label="Public consumer credit data",
        valid_ranges={"person_age": (18, 100), "person_emp_length": (0, 60)},
        excluded={"exact_duplicate_rows": 1},
    )
    assert report["rows"] == 5 and report["duplicate_rows"] == 1
    assert report["target"]["positives"] == 2
    assert report["missing_values"]["person_emp_length"]["rows"] == 2
    assert report["invalid_values"]["person_age"]["out_of_range_rows"] == 1
    assert report["invalid_values"]["person_emp_length"]["out_of_range_rows"] == 1
    assert "Not Pakistani SME" in report["not_this"]


@pytest.mark.skipif(load_data_quality() is None, reason="data quality report not recorded")
def test_the_recorded_data_quality_report(client: TestClient) -> None:
    body = client.get("/model/data-quality").json()
    assert body == json.loads(DATA_QUALITY_PATH.read_text(encoding="utf-8"))
    assert body["rows"] == 32_581 and body["duplicate_rows"] == 165
    assert body["excluded_rows"] == {"exact_duplicate_rows": 165}
    assert "not Pakistani SME" in body["dataset_type"]
    assert body["invalid_values"]["person_age"]["out_of_range_rows"] > 0
    assert set(body["learned_parameters_from_training_split"]) == {"medians", "clip_bounds"}


# --- P. subgroup analysis edge cases ------------------------------------------------


def test_small_or_one_sided_groups_are_marked_insufficient() -> None:
    small = group_row("tiny", np.array([90.0, 30.0]), np.array([0.1, 0.7]), np.array([0.1, 0.6]), np.array([0, 1]))
    assert small["sample_status"] == INSUFFICIENT and small["auc_roc"] is None

    rows = MIN_GROUP_ROWS * 2
    no_defaults = group_row(
        "none", np.full(rows, 80.0), np.full(rows, 0.2), np.full(rows, 0.1), np.zeros(rows, dtype=int)
    )
    assert no_defaults["sample_status"] == INSUFFICIENT
    assert no_defaults["recall"] is None and no_defaults["auc_roc"] is None

    rng = np.random.default_rng(0)
    y = (rng.uniform(size=rows) < 0.3).astype(int)
    raw = np.clip(0.3 + 0.4 * y + rng.normal(0, 0.2, rows), 0, 1)
    enough = group_row("ok", 100 * (1 - raw), raw, raw, y)
    assert enough["sample_status"] == "Sufficient"
    assert 0.5 < enough["auc_roc"] <= 1.0
    flagged = raw >= 0.5
    assert enough["recall"] == pytest.approx((flagged & (y == 1)).sum() / y.sum())
    assert enough["precision"] == pytest.approx((flagged & (y == 1)).sum() / flagged.sum())


@pytest.mark.skipif(not EVALUATION or "final_test" not in EVALUATION, reason="not evaluated")
def test_the_recorded_subgroup_analysis_is_on_the_final_test_set(client: TestClient) -> None:
    body = client.get("/model/fairness").json()
    assert body["title"] == "Subgroup Performance Analysis"
    assert body["evaluated_on"] == "final test set"
    assert body["rows"] == EVALUATION["final_test"]["rows"]
    assert "does not establish" in body["interpretation"] or "do not establish" in body["interpretation"]
    statuses = {row["sample_status"] for block in body["attributes"] for row in block["groups"]}
    assert statuses <= {"Sufficient", INSUFFICIENT}


# --- Q. model page API --------------------------------------------------------------


def test_the_model_card_endpoint_separates_model_and_policy(client: TestClient) -> None:
    body = client.get("/model/card").json()
    assert body["serving_engine"] == "surrogate"  # tests pin the fallback formula
    assert "not derived from, or optimised on" in body["policy_note"]
    assert any("not validated for Pakistani SME lending" in line for line in body["limitations"])
    assert body["model_card"] == "docs/model_card.md"
    if METADATA and "training_protocol_version" in METADATA:
        assert body["status"]["dataset_type"] == METADATA["dataset_type_label"]
        assert body["status"]["dataset_sha256"] == METADATA["dataset_sha256"]
    if EVALUATION and "final_test" in EVALUATION:
        assert body["performance"]["final_test_raw"]["auc_roc"] == EVALUATION["final_test"]["metrics_raw"]["auc_roc"]
        assert body["calibration"]["display_only"] is True
        assert body["evaluation_thresholds"]["raw_probability"] == 0.5


def test_model_page_routes_need_a_login(client: TestClient) -> None:
    for path in ("/model/card", "/model/data-quality", "/model/feature-contract"):
        assert client.get(path, headers={"Authorization": ""}).status_code == 401


def test_drift_is_labelled_as_a_demo_reference(client: TestClient) -> None:
    response = client.get("/model/drift")
    if response.status_code == 404:
        pytest.skip("no reference distributions recorded")
    body = response.json()
    assert body["reference_label"] == "Reference / Demo Distribution"
    assert "not production drift monitoring" in body["reference_note"]


def test_comparison_file_is_the_2_2_protocol_when_present() -> None:
    comparison = load_model_comparison()
    if not comparison or "labels" not in comparison:
        pytest.skip("comparison not recorded under 2.2")
    assert COMPARISON_PATH.exists()
    assert "train-only preprocessing" in comparison["protocol"]


def test_surrogate_explanations_keep_their_neutral_base_value(client: TestClient) -> None:
    body = client.post("/score", json=MID_APPLICANT).json()
    assert body["explanation"]["base_value"] == ScoringService().base_value == 50.0
