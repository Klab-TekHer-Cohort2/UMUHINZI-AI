"""Tests for the Africa's Talking USSD webhook."""

import logging

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import storage
from app.main import app
from app.services import alerts as alert_service
from app.services import webhooks

client = TestClient(app)
PHONE = "+250788123456"


@pytest.fixture
def ussd_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "ussd-test.db")
    monkeypatch.setattr(config, "OUTBREAK_THRESHOLD", 3)
    monkeypatch.setattr(config, "OUTBREAK_WINDOW_DAYS", 7)
    storage.init_db()
    webhooks.clear_all_sessions()
    yield
    webhooks.clear_all_sessions()


def post(session: str, text: str, phone: str = PHONE):
    return client.post(
        "/ussd",
        data={
            "sessionId": session,
            "serviceCode": "*123#",
            "phoneNumber": phone,
            "text": text,
        },
    )


def walk(session: str, texts: list[str], phone: str = PHONE) -> list[str]:
    replies = []
    for text in texts:
        response = post(session, text, phone)
        assert response.status_code == 200, response.text
        assert response.text.startswith(("CON ", "END "))
        assert len(response.text) <= 182, (text, response.text)
        replies.append(response.text)
    return replies


def test_initial_screen_offers_language_choice(ussd_db):
    reply = walk("s1", [""])[0]

    assert reply.startswith("CON ")
    assert "Ikinyarwanda" in reply
    assert "English" in reply


def test_full_session_with_numbered_symptom_saves_hashed_report(ussd_db):
    replies = walk(
        "s2",
        ["", "1", "1*1", "1*1*1", "1*1*1*1", "1*1*1*1*1"],
    )

    assert all(reply.startswith("CON ") for reply in replies[:-1])
    assert replies[-1].startswith("END ")
    assert "Twahisemo" not in replies[-1]  # short USSD wording is used
    assert "Kura udukoko" in replies[-1]

    reports = storage.list_recent_diagnoses()
    assert len(reports) == 1
    assert reports[0]["pest_id"] == "fall_armyworm"
    assert reports[0]["sector"] == "Kacyiru"
    assert reports[0]["district"] == "Gasabo"
    assert reports[0]["reporter_hash"] == storage.hash_identifier(PHONE)
    assert PHONE not in repr(reports)


def test_full_session_with_typed_symptom(ussd_db):
    replies = walk(
        "s3",
        [
            "",
            "1",
            "1*1",
            "1*1*1",
            "1*1*1*1",
            "1*1*1*1*7",
            "1*1*1*1*7*isazi y'ibishyimbo amababi y'umuhondo",
        ],
    )

    assert replies[-1].startswith("END ")
    assert storage.list_recent_diagnoses()[0]["pest_id"] == "bean_fly"


def test_known_pest_menu_uses_knowledge_base(ussd_db):
    replies = walk("s4", ["", "1", "1*1", "1*1*1", "1*1*1*2", "1*1*1*2*4"])

    assert replies[-1].startswith("END ")
    report = storage.list_recent_diagnoses()[0]
    assert report["pest_id"] == "bean_fly"
    assert report["reporter_hash"] == storage.hash_identifier(PHONE)


def test_alerts_menu_shows_active_alert_in_sector(ussd_db):
    for _ in range(3):
        storage.save_diagnosis(
            reporter_hash=storage.hash_identifier("other-farmer"),
            pest_id="fall_armyworm",
            sector="Kacyiru",
            district="Gasabo",
        )
    alert_service.check_outbreak("fall_armyworm", "Kacyiru", "Gasabo")
    reports_before = len(storage.list_recent_diagnoses())

    replies = walk("s5", ["", "1", "1*1", "1*1*1", "1*1*1*3"])

    assert replies[-1].startswith("END ")
    assert "Ibyihutirwa" in replies[-1]
    assert "Kacyiru" in replies[-1]
    assert len(storage.list_recent_diagnoses()) == reports_before


def test_three_ussd_reports_trigger_outbreak_dry_run(ussd_db, caplog):
    path = ["", "1", "1*1", "1*1*1", "1*1*1*1", "1*1*1*1*1"]

    with caplog.at_level(logging.INFO):
        for index in range(3):
            replies = walk(f"outbreak-{index}", path)

    assert replies[-1].startswith("END ")
    reports = storage.list_recent_diagnoses()
    assert len(reports) == 3

    alerts = storage.list_alerts()
    assert len(alerts) == 1
    assert alerts[0]["pest_id"] == "fall_armyworm"
    assert alerts[0]["sector"] == "Kacyiru"
    assert "DRY-RUN" in caplog.text
    assert PHONE not in caplog.text


def test_typed_district_and_sector_are_accepted(ussd_db):
    replies = walk(
        "s6",
        [
            "",
            "1",
            "1*4*Rulindo",
            "1*4*Rulindo*4",
            "1*4*Rulindo*4*Kacyiru",
            "1*4*Rulindo*4*Kacyiru*1",
            "1*4*Rulindo*4*Kacyiru*1*1",
        ],
    )

    assert replies[-1].startswith("CON ")
    state = webhooks.get_session(webhooks.hashed_key("s6", PHONE))
    assert state.district == "Rulindo"
    assert state.sector == "Kacyiru"
    assert state.stage == "symptoms"
