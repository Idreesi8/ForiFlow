"""Real API workflows agree at Pakistan midnight, regardless of UTC's date."""
from datetime import date, datetime, timedelta, timezone

import pytest

import business_time
from business_time import as_utc, business_date
from models.database import Alert, Application, EWSTracking
from tests.conftest import STRONG_APPLICANT, decide


@pytest.mark.parametrize("instant,expected", [
    ("2026-10-25T18:59:59.999999+00:00", "2026-10-25"),
    ("2026-10-25T19:00:00+00:00", "2026-10-26"),
    ("2026-10-31T19:00:00+00:00", "2026-11-01"),
    ("2026-12-31T19:00:00+00:00", "2027-01-01"),
    ("2028-02-28T19:00:00+00:00", "2028-02-29"),
    ("2026-10-26T01:30:00+05:00", "2026-10-26"),
])
def test_calendar_boundaries(instant, expected):
    assert business_date(datetime.fromisoformat(instant)).isoformat() == expected


def test_naive_sqlite_instants_are_utc_and_aware_offsets_are_preserved():
    naive = datetime(2026, 10, 25, 20, 30)
    offset = datetime(2026, 10, 26, 1, 30, tzinfo=timezone(timedelta(hours=5)))
    assert as_utc(naive) == as_utc(offset)
    assert business_date(naive) == business_date(offset) == date(2026, 10, 26)


@pytest.fixture
def clock(monkeypatch):
    current = [datetime(2026, 10, 25, 20, tzinfo=timezone.utc)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0].astimezone(tz) if tz else current[0].replace(tzinfo=None)

    monkeypatch.setattr(business_time, "datetime", Clock)
    return current


def facility(client, db_session_factory, created=None):
    response = client.post("/score", json=STRONG_APPLICANT)
    assert response.status_code == 201, response.text
    identifier = response.json()["application_id"]
    decide(client, identifier)
    if created is not None:
        with db_session_factory() as db:
            row = db.get(Application, identifier)
            row.created_at = row.reviewed_at = created
            db.commit()
    return identifier


def observation(identifier, **fields):
    return {"borrower_id": identifier, "month_number": 1, "installment_status": "Late 30-59",
            "days_late": 31, "bureau_balance": 1, "pos_cash_balance": 850_000, **fields}


@pytest.mark.parametrize("endpoint", ["/ews/observations", "/ews/monitor"])
def test_default_and_explicit_today_work_before_utc_midnight(client, db_session_factory, clock, endpoint):
    identifier = facility(client, db_session_factory)
    result = client.post(endpoint, json=observation(identifier))
    assert result.status_code == 201, result.text
    row = result.json()["tracking"]
    assert row["observation_date"] == "2026-10-26"
    assert datetime.fromisoformat(row["created_at"]).replace(tzinfo=timezone.utc) == clock[0]
    explicit = client.post(endpoint, json=observation(identifier, month_number=2, observation_date="2026-10-26"))
    assert explicit.status_code == 201, explicit.text
    future = client.post(endpoint, json=observation(identifier, month_number=3, observation_date="2026-10-27"))
    assert future.status_code == 422 and "future" in future.text


def test_observation_cannot_precede_the_pakistan_application_day(client, db_session_factory, clock):
    identifier = facility(client, db_session_factory, datetime(2026, 10, 25, 19, 30, tzinfo=timezone.utc))
    rejected = client.post("/ews/observations", json=observation(identifier, observation_date="2026-10-25"))
    assert rejected.status_code == 422 and "before application" in rejected.text
    assert "2026-10-26" in rejected.text
    accepted = client.post("/ews/observations", json=observation(identifier, observation_date="2026-10-26"))
    assert accepted.status_code == 201, accepted.text


def test_correction_preserves_recorded_calendar_date_and_rejects_future_day(client, db_session_factory, clock):
    identifier = facility(client, db_session_factory)
    first = client.post("/ews/observations", json=observation(identifier)).json()["tracking"]
    clock[0] += timedelta(days=1)
    body = {key: value for key, value in observation(identifier).items() if key not in ("borrower_id", "month_number")}
    body["correction_reason"] = "Verified the synthetic source receipt."
    corrected = client.post(f"/ews/observations/{first['id']}/correct", json=body)
    assert corrected.status_code == 201, corrected.text
    row = corrected.json()["tracking"]
    assert row["observation_date"] == "2026-10-26"
    future = client.post(f"/ews/observations/{row['id']}/correct", json={**body, "observation_date": "2026-10-28"})
    assert future.status_code == 422 and "future" in future.text


@pytest.mark.parametrize("include_date", [False, True])
def test_correction_can_retain_a_legacy_utc_calendar_date_without_shifting_history(client, db_session_factory, clock, include_date):
    identifier = facility(client, db_session_factory)
    first = client.post("/ews/observations", json=observation(identifier)).json()["tracking"]
    with db_session_factory() as db:
        # Simulate a row accepted under the old UTC-day rule at 01:00 PKT.
        db.get(EWSTracking, first["id"]).observation_date = date(2026, 10, 25)
        db.commit()
    body = {"installment_status": "On Time", "bureau_balance": 1, "pos_cash_balance": 850_000,
            "correction_reason": "Verified the amount; retain the recorded source date."}
    if include_date:
        body["observation_date"] = "2026-10-25"
    corrected = client.post(f"/ews/observations/{first['id']}/correct", json=body)
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["tracking"]["observation_date"] == "2026-10-25"
    invalid = client.post(f"/ews/observations/{corrected.json()['tracking']['id']}/correct",
                          json={**body, "observation_date": "2026-10-24"})
    assert invalid.status_code == 422 and "before application" in invalid.text
    rows = client.get(f"/ews/facilities/{identifier}/observations").json()
    assert len(rows) == 2 and all(row["observation_date"] == "2026-10-25" for row in rows)


@pytest.mark.parametrize("step,extra", [
    ("due-date", {}), ("assign", {"assigned_to": "admin"}),
    ("action-required", {"action_note": "Inspect synthetic evidence."}),
])
def test_alert_deadlines_use_pakistan_today(client, db_session_factory, clock, step, extra):
    identifier = facility(client, db_session_factory)
    alert = client.post("/ews/observations", json=observation(identifier)).json()["alert"]
    base = f"/ews/alerts/{alert['id']}"
    assert client.post(base + "/acknowledge", json={"note": "Seen."}).status_code == 200
    rejected = client.post(base + "/" + step, json={**extra, "due_date": "2026-10-25"})
    assert rejected.status_code == 422 and "past" in rejected.text
    accepted = client.post(base + "/" + step, json={**extra, "due_date": "2026-10-26"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["is_overdue"] is False


def test_feed_overview_state_and_desk_agree_at_exact_midnight(client, db_session_factory, clock):
    identifier = facility(client, db_session_factory)
    raised = client.post("/ews/observations", json=observation(identifier)).json()["alert"]
    with db_session_factory() as db:
        db.get(Alert, raised["id"]).action_due_date = date(2026, 10, 25)
        db.commit()
    for instant, expected in [(datetime(2026, 10, 25, 18, 59, 59, tzinfo=timezone.utc), False),
                              (datetime(2026, 10, 25, 19, tzinfo=timezone.utc), True)]:
        clock[0] = instant
        feed = client.get("/ews/alerts").json()[0]
        overview = client.get("/ews/overview").json()
        state = client.get(f"/ews/facilities/{identifier}/state").json()
        desk = client.get("/portfolio/action-desk", params={"kind": "alert"}).json()
        assert feed["is_overdue"] is expected
        assert overview["overdue_actions"] == int(expected)
        assert overview["rows"][0]["overdue"] is expected
        assert state["open_alert"]["is_overdue"] is expected
        assert (desk["items"][0]["priority"] == "urgent") is expected


def test_reminder_anchor_is_the_pakistan_approval_day_and_rolls_over_at_midnight(client, db_session_factory, clock):
    identifier = facility(client, db_session_factory, datetime(2026, 10, 31, 20, tzinfo=timezone.utc))
    # UTC Oct 31 is Nov 1 in Pakistan, so the first monthly due date is Dec 1.
    clock[0] = datetime(2026, 11, 30, 19, tzinfo=timezone.utc)
    today = client.get("/portfolio/reminders").json()[0]
    assert today["application_id"] == identifier
    assert today["due_date"] == "2026-12-01" and today["days_until_due"] == 0
    assert today["kind"] == "due_soon"
    clock[0] = datetime(2026, 12, 1, 19, tzinfo=timezone.utc)
    overdue = client.get("/portfolio/reminders").json()[0]
    assert overdue["due_date"] == "2026-12-01" and overdue["days_until_due"] == -1
    assert overdue["kind"] == "overdue"
