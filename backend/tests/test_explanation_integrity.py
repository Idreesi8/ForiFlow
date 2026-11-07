"""Historical XAI must reproduce its original assessment, never today's model."""
import json

import pytest
from sqlalchemy import select

from main import app
from models.database import Application, Base, ModelVersion
from services.scoring_service import ScoringService, get_scoring_service
from tests.conftest import MID_APPLICANT


def snapshot(factory):
    with factory() as db:
        return {
            table.name: sorted(json.dumps(dict(row), default=str, sort_keys=True)
                               for row in db.execute(select(table)).mappings())
            for table in Base.metadata.sorted_tables
        }


@pytest.mark.parametrize("method,url", [
    ("get", ""), ("post", ""), ("post", "?refresh=true"),
])
@pytest.mark.parametrize("damage", [
    "model_version", "scoring_engine", "artifact", "registry_version",
    "registry_engine", "missing_model_link", "missing_policy", "invalid_policy",
    "nonfinite_policy", "score", "decision", "risk_band",
])
def test_unverifiable_regeneration_is_blocked_without_any_writes(
    client, db_session_factory, method, url, damage,
):
    scored = client.post("/score", json=MID_APPLICANT).json()
    key = scored["application_id"]
    with db_session_factory() as db:
        case = db.get(Application, key)
        case.shap_explanation_json = None
        source = db.get(ModelVersion, case.model_version_id)
        if damage == "model_version": case.model_version = "older-model"
        elif damage == "scoring_engine": case.scoring_engine = "ml"
        elif damage == "artifact": source.artifact_sha256 = "a" * 64
        elif damage == "registry_version": source.version = "older-model"
        elif damage == "registry_engine": source.engine = "ml"
        elif damage == "missing_model_link": case.model_version_id = None
        elif damage == "missing_policy": case.policy_evaluation = None
        elif damage == "invalid_policy":
            case.policy_evaluation = {"bands": {"decline_max_score": 80, "manual_review_max_score": 40}}
        elif damage == "nonfinite_policy":
            case.policy_evaluation = {"bands": {"decline_max_score": "NaN", "manual_review_max_score": 70}}
        elif damage == "score": case.risk_score += 1
        elif damage == "decision": case.decision = "Rejected"
        elif damage == "risk_band": case.risk_band = "High Risk"
        db.commit()
    before = snapshot(db_session_factory)
    response = getattr(client, method)(f"/explain/{key}{url}")
    assert response.status_code == 409, response.text
    assert "explanation" in response.json()["detail"]
    assert snapshot(db_session_factory) == before


def test_saved_explanation_survives_model_change_but_refresh_is_blocked(client, db_session_factory):
    scored = client.post("/score", json=MID_APPLICANT).json()
    # Same version label, different weights and artifact fingerprint. Even if
    # the score happened to match, the attribution must not silently change.
    changed = ScoringService(weights={"payment_history_score": 1.0})
    app.dependency_overrides[get_scoring_service] = lambda: changed
    before = snapshot(db_session_factory)
    for method in (client.get, client.post):
        assert method(f"/explain/{scored['application_id']}").json() == scored["explanation"]
    assert client.post(f"/explain/{scored['application_id']}?refresh=true").status_code == 409
    assert snapshot(db_session_factory) == before


@pytest.mark.parametrize("cached", [None, "{unreadable"])
def test_original_model_can_recover_missing_or_unreadable_explanation(client, db_session_factory, cached):
    scored = client.post("/score", json=MID_APPLICANT).json()
    key = scored["application_id"]
    with db_session_factory() as db:
        db.get(Application, key).shap_explanation_json = cached
        db.commit()
    before = snapshot(db_session_factory)
    assert client.get(f"/explain/{key}").json() == scored["explanation"]
    assert snapshot(db_session_factory) == before  # GET never repairs records.
    assert client.post(f"/explain/{key}").json() == scored["explanation"]
    with db_session_factory() as db:
        assert json.loads(db.get(Application, key).shap_explanation_json) == scored["explanation"]


def test_unreadable_historical_explanation_is_not_replaced_by_new_model(client, db_session_factory):
    scored = client.post("/score", json=MID_APPLICANT).json()
    key = scored["application_id"]
    with db_session_factory() as db:
        case = db.get(Application, key)
        case.shap_explanation_json = "{unreadable"
        db.commit()
    changed = ScoringService(weights={"payment_history_score": 1.0})
    app.dependency_overrides[get_scoring_service] = lambda: changed
    before = snapshot(db_session_factory)
    assert client.get(f"/explain/{key}").status_code == 409
    assert client.post(f"/explain/{key}").status_code == 409
    assert snapshot(db_session_factory) == before


@pytest.mark.parametrize("damage", ["residual", "nonfinite"])
def test_regeneration_rejects_invalid_attributions(client, db_session_factory, monkeypatch, damage):
    scored = client.post("/score", json=MID_APPLICANT).json()
    original = ScoringService.build_explanation

    def broken(self, *args, **kwargs):
        explanation = original(self, *args, **kwargs)
        return explanation.model_copy(update={"base_value": (
            explanation.base_value + 5 if damage == "residual" else float("nan")
        )})

    monkeypatch.setattr(ScoringService, "build_explanation", broken)
    before = snapshot(db_session_factory)
    assert client.post(f"/explain/{scored['application_id']}?refresh=true").status_code == 409
    assert snapshot(db_session_factory) == before


def test_trained_model_reproduces_original_shap_without_writes(ml_client, db_session_factory):
    scored = ml_client.post("/score", json=MID_APPLICANT).json()
    key = scored["application_id"]
    with db_session_factory() as db:
        db.get(Application, key).shap_explanation_json = None
        db.commit()
    before = snapshot(db_session_factory)
    response = ml_client.get(f"/explain/{key}")
    assert response.status_code == 200, response.text
    assert response.json() == scored["explanation"]
    assert snapshot(db_session_factory) == before
