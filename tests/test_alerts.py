"""Tests for the outbreak early-warning rule and its API endpoints."""

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import storage
from app.main import app
from app.services import alerts

client = TestClient(app)
PEST = "fall_armyworm"


@pytest.fixture
def outbreak_db(tmp_path, monkeypatch):
    db_path = tmp_path / "outbreak-test.db"
    monkeypatch.setattr(config, "DB_FILE", db_path)
    monkeypatch.setattr(config, "OUTBREAK_THRESHOLD", 3)
    monkeypatch.setattr(config, "OUTBREAK_WINDOW_DAYS", 7)
    storage.init_db()
    yield db_path


def _report(sector="Kacyiru", district="Gasabo", created_at=None, pest_id=PEST):
    return storage.save_diagnosis(
        reporter_hash=storage.hash_identifier("session-demo"),
        pest_id=pest_id,
        sector=sector,
        district=district,
        created_at=created_at,
    )


def test_below_threshold_does_not_create_alert(outbreak_db):
    _report()
    _report()

    assert alerts.check_outbreak(PEST, "Kacyiru", "Gasabo") is None
    assert storage.list_alerts() == []


def test_threshold_creates_one_dry_run_alert(outbreak_db, caplog):
    for _ in range(3):
        _report()

    alert = alerts.check_outbreak(PEST, "Kacyiru", "Gasabo")

    assert alert is not None
    assert alert["created"] is True
    assert alert["report_count"] == 3
    assert alert["status"] == "active"
    assert "Kacyiru" in alert["message_rw"]
    assert "fall_armyworm" not in alert["message_rw"]

    stored = storage.list_alerts()
    assert len(stored) == 1
    assert stored[0]["message_rw"] == alert["message_rw"]
    assert "DRY-RUN" in caplog.text


def test_alert_is_not_duplicated_while_active(outbreak_db):
    for _ in range(3):
        _report()

    first = alerts.check_outbreak(PEST, "Kacyiru", "Gasabo")
    assert first["created"] is True

    _report()
    second = alerts.check_outbreak(PEST, "Kacyiru", "Gasabo")

    assert second is not None
    assert second["created"] is False
    assert len(storage.list_alerts()) == 1


def test_other_sector_does_not_trigger(outbreak_db):
    for _ in range(3):
        _report(sector="Kacyiru")

    assert alerts.check_outbreak(PEST, "Remera", "Gasabo") is None


def test_reports_outside_window_are_ignored(outbreak_db):
    _report(created_at="2025-01-01T00:00:00+00:00")
    _report(created_at="2025-01-02T00:00:00+00:00")
    _report()

    assert alerts.check_outbreak(PEST, "Kacyiru", "Gasabo") is None


def test_diagnose_endpoint_reports_and_triggers_alert(outbreak_db):
    body = {
        "text": "amababi y'ibigori arashye kandi afite uduhumbi",
        "phone": "+250788123456",
        "sector": "Kacyiru",
        "district": "Gasabo",
    }

    for _ in range(3):
        response = client.post("/diagnose", json=body)
        assert response.status_code == 200

    final = response.json()
    assert final["diagnosis"]["pest_id"] == PEST
    assert final["outbreak_alert"]["created"] is True

    alerts_response = client.get("/alerts")
    assert alerts_response.status_code == 200
    payload = alerts_response.json()
    assert payload["count"] == 1
    assert payload["alerts"][0]["sector"] == "Kacyiru"

    reports_response = client.get("/reports")
    assert reports_response.status_code == 200
    reports = reports_response.json()["reports"]
    assert len(reports) == 3
    assert all(report["reporter_hash"] != "+250788123456" for report in reports)
