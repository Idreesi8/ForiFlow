"""Which model scored each application, and that a fallback is never hidden."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from main import app
from models.database import Application, AuditLog, ModelVersion
from services import model_registry, scoring_service
from services.audit_service import Action
from services.scoring_service import ScoringService, get_scoring_service
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT


def _stored(db_session_factory, application_id: int) -> Application:
    db = db_session_factory()
    try:
        return db.get(Application, application_id)
    finally:
        db.close()


# --- every score records its model --------------------------------------------------


def test_a_score_stores_its_model_version_and_engine(client: TestClient, db_session_factory) -> None:
    body = client.post("/score", json=STRONG_APPLICANT).json()

    assert body["model_version"] == "surrogate-linear-v1"
    assert body["scoring_engine"] == "surrogate"

    row = _stored(db_session_factory, body["application_id"])
    assert row.model_version == "surrogate-linear-v1"
    assert row.scoring_engine == "surrogate"
    assert row.model_version_id is not None

    summary = client.get(f"/score/applications/{body['application_id']}").json()
    assert summary["model_version"] == body["model_version"]
    assert summary["scoring_engine"] == "surrogate"
    assert all(
        item["model_version"] and item["scoring_engine"]
        for item in client.get("/score/applications").json()
    )


def test_the_trained_ensemble_records_itself_with_its_fingerprint(
    ml_client: TestClient, ml_service, db_session_factory
) -> None:
    body = ml_client.post("/score", json=STRONG_APPLICANT).json()

    assert body["scoring_engine"] == "ml"
    assert body["model_version"] == ml_service.model_version
    assert body["model_version"].startswith("ensemble-xgb-rf-")

    row = _stored(db_session_factory, body["application_id"])
    assert (row.model_version, row.scoring_engine) == (ml_service.model_version, "ml")

    active = ml_client.get("/model/versions/active").json()
    assert active["id"] == row.model_version_id
    assert active["engine"] == "ml" and active["is_active"] is True
    assert active["fallback_reason"] is None
    assert len(active["artifact_sha256"]) == 64
    assert active["artifact_sha256"] == ml_service.artifact_sha256
    assert active["training_dataset"] == ml_service.metadata["dataset"]
    assert active["feature_set"] == ml_service.feature_names
    assert active["trained_at"] == ml_service.metadata["trained_at"]
    assert active["metrics"]["holdout_auc_roc"] == pytest.approx(
        ml_service.metadata["holdout"]["auc"]
    )
    assert active["applications_scored"] == 1


def test_the_artifact_fingerprint_follows_the_files(ml_service) -> None:
    import hashlib

    from ml.features import FEATURE_NAMES_PATH, MODEL_PATH, SCALER_PATH, SHAP_EXPLAINER_PATH

    digest = hashlib.sha256()
    for path in (MODEL_PATH, SCALER_PATH, SHAP_EXPLAINER_PATH, FEATURE_NAMES_PATH):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    assert ml_service.artifact_sha256 == digest.hexdigest()


def test_a_changed_formula_is_a_different_model_record(db_session_factory) -> None:
    standard = ScoringService()
    altered = ScoringService(weights={"payment_history_score": 1.0})
    assert standard.artifact_sha256 == ScoringService().artifact_sha256
    assert altered.artifact_sha256 != standard.artifact_sha256

    db = db_session_factory()
    try:
        first = model_registry.ensure_registered(db, standard)
        second = model_registry.ensure_registered(db, altered)
        db.commit()
        assert first.id != second.id
        assert first.version == second.version  # same label, different fingerprint
        db.refresh(first)
        assert (first.status, second.status) == ("retired", "active")
    finally:
        db.close()


# --- history is kept ----------------------------------------------------------------


def test_an_application_keeps_the_model_it_was_scored_with(
    ml_client: TestClient, ml_service, db_session_factory
) -> None:
    """Score with the fallback, then with the trained model: neither rewrites the other."""
    app.dependency_overrides[get_scoring_service] = lambda: ScoringService()
    early = ml_client.post("/score", json=MID_APPLICANT).json()
    app.dependency_overrides[get_scoring_service] = lambda: ml_service
    late = ml_client.post(
        "/score", json={**MID_APPLICANT, "borrower_public_id": early["borrower_public_id"]}
    ).json()

    early_row = _stored(db_session_factory, early["application_id"])
    late_row = _stored(db_session_factory, late["application_id"])
    assert (early_row.model_version, early_row.scoring_engine) == ("surrogate-linear-v1", "surrogate")
    assert (late_row.model_version, late_row.scoring_engine) == (ml_service.model_version, "ml")
    assert early_row.model_version_id != late_row.model_version_id
    assert early_row.risk_score == early["risk_score"]

    # Recomputing the explanation with the newer model does not touch the record.
    ml_client.post(f"/explain/{early['application_id']}?refresh=true")
    again = _stored(db_session_factory, early["application_id"])
    assert (again.model_version, again.scoring_engine, again.risk_score) == (
        "surrogate-linear-v1",
        "surrogate",
        early["risk_score"],
    )

    history = ml_client.get(f"/borrowers/{early['borrower_public_id']}/history").json()
    assert history["summary"]["model_versions_used"] == [
        "surrogate-linear-v1",
        ml_service.model_version,
    ]
    assert history["summary"]["scoring_engines_used"] == ["surrogate", "ml"]

    versions = {row["version"]: row for row in ml_client.get("/model/versions").json()}
    assert versions[ml_service.model_version]["is_active"] is True
    assert versions["surrogate-linear-v1"]["is_active"] is False
    assert versions["surrogate-linear-v1"]["applications_scored"] == 1
    assert versions[ml_service.model_version]["applications_scored"] == 1


def test_only_one_model_is_active_and_switching_is_audited(
    ml_client: TestClient, ml_service, db_session_factory
) -> None:
    app.dependency_overrides[get_scoring_service] = lambda: ScoringService()
    ml_client.post("/score", json=STRONG_APPLICANT)
    app.dependency_overrides[get_scoring_service] = lambda: ml_service
    ml_client.post("/score", json=STRONG_APPLICANT)
    ml_client.post("/score", json=MID_APPLICANT)

    db = db_session_factory()
    try:
        active = db.scalars(select(ModelVersion).where(ModelVersion.status == "active")).all()
        registered = db.scalars(select(AuditLog).where(AuditLog.action == Action.MODEL_REGISTERED)).all()
        activated = db.scalars(select(AuditLog).where(AuditLog.action == Action.MODEL_ACTIVATED)).all()
    finally:
        db.close()
    assert [row.version for row in active] == [ml_service.model_version]
    assert len(registered) == 2  # once each, not once per score
    assert len(activated) == 2
    assert activated[-1].previous_state == {"active": ["surrogate-linear-v1"]}
    assert activated[-1].new_state["active"] == ml_service.model_version
    assert all(entry.username == "system" for entry in registered)


def test_model_versions_need_a_login_and_start_empty(client: TestClient) -> None:
    assert client.get("/model/versions", headers={"Authorization": ""}).status_code == 401
    assert client.get("/model/versions").json() == []
    assert client.get("/model/versions/active").status_code == 404


# --- a fallback is never hidden -----------------------------------------------------


@pytest.fixture(name="fresh_engine")
def fresh_engine_fixture(monkeypatch):
    """Let a test resolve the scoring engine again, then restore the cached one."""
    get_scoring_service.cache_clear()
    yield monkeypatch
    get_scoring_service.cache_clear()


def test_a_pinned_surrogate_says_so(fresh_engine) -> None:
    fresh_engine.setenv("FORIFLOW_SCORING_ENGINE", "surrogate")
    service = get_scoring_service()
    assert (service.engine, service.fallback_reason) == ("surrogate", "pinned")


def test_missing_artefacts_are_named_as_the_reason(fresh_engine) -> None:
    fresh_engine.setenv("FORIFLOW_SCORING_ENGINE", "auto")
    fresh_engine.setattr("ml.features.artifacts_available", lambda: False)
    service = get_scoring_service()
    assert (service.engine, service.fallback_reason) == ("surrogate", "artifacts_missing")


def test_a_model_that_fails_to_load_is_recorded_as_a_failed_load(
    fresh_engine, client: TestClient, db_session_factory
) -> None:
    """The case the audit found: artefacts present, loading them fails, scoring goes on."""

    def broken(cls):
        raise RuntimeError("unpickling failed")

    fresh_engine.setenv("FORIFLOW_SCORING_ENGINE", "auto")
    fresh_engine.setattr("ml.features.artifacts_available", lambda: True)
    fresh_engine.setattr(scoring_service.MLScoringService, "from_artifacts", classmethod(broken))
    get_scoring_service.cache_clear()  # the client's startup resolved it already
    service = get_scoring_service()
    assert (service.engine, service.fallback_reason) == ("surrogate", "load_failed")

    # /health reports it instead of looking normal.
    health = client.get("/health").json()
    assert health["scoring_engine"] == "surrogate"
    assert health["scoring_fallback_reason"] == "load_failed"
    assert health["model_version"] == "surrogate-linear-v1"

    # And a score made in that state carries it everywhere it is stored.
    app.dependency_overrides[get_scoring_service] = lambda: service
    body = client.post("/score", json=STRONG_APPLICANT).json()
    assert body["scoring_engine"] == "surrogate"
    assert _stored(db_session_factory, body["application_id"]).scoring_engine == "surrogate"

    active = client.get("/model/versions/active").json()
    assert (active["engine"], active["fallback_reason"]) == ("surrogate", "load_failed")
    scored = client.get("/audit/logs", params={"action": "application.scored"}).json()[0]
    assert scored["details"]["scoring_engine"] == "surrogate"
    assert scored["details"]["fallback_reason"] == "load_failed"
    activated = client.get("/audit/logs", params={"action": "model.activated"}).json()[0]
    assert activated["new_state"]["fallback_reason"] == "load_failed"


def test_demanding_the_trained_model_fails_loudly_instead_of_falling_back(fresh_engine) -> None:
    def broken(cls):
        raise RuntimeError("unpickling failed")

    fresh_engine.setenv("FORIFLOW_SCORING_ENGINE", "ml")
    fresh_engine.setattr(scoring_service.MLScoringService, "from_artifacts", classmethod(broken))
    with pytest.raises(RuntimeError, match="unpickling failed"):
        get_scoring_service()


def test_health_reports_the_engine(client: TestClient) -> None:
    health = client.get("/health").json()
    assert health["scoring_engine"] in ("ml", "surrogate")
    assert health["model_version"]
    assert (health["scoring_fallback_reason"] is None) == (health["scoring_engine"] == "ml")


def test_the_stored_explanation_names_the_same_model(client: TestClient, db_session_factory) -> None:
    body = client.post("/score", json=STRONG_APPLICANT).json()
    row = _stored(db_session_factory, body["application_id"])
    assert json.loads(row.shap_explanation_json)["model_version"] == row.model_version
