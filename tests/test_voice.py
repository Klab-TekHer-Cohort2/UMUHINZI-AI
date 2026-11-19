"""Tests for the Africa's Talking voice webhook (XML callbacks)."""

import logging

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import storage
from app.main import app
from app.services import alerts as alert_service
from app.services import asr, tts, voice, webhooks

client = TestClient(app)
PHONE = "+250788123456"
RECORDING_URL = "https://recordings.example.test/call-1.wav"


@pytest.fixture
def voice_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "voice-test.db")
    monkeypatch.setattr(config, "OUTBREAK_THRESHOLD", 3)
    monkeypatch.setattr(config, "OUTBREAK_WINDOW_DAYS", 7)
    storage.init_db()
    webhooks.clear_all_sessions()
    tts.clear_cache()
    yield
    webhooks.clear_all_sessions()
    tts.clear_cache()


def post(session: str = "voice-1", **overrides):
    data = {
        "sessionId": session,
        "isActive": "1",
        "callerNumber": PHONE,
        "dtmfDigits": "",
        "recordingUrl": "",
    }
    data.update(overrides)
    return client.post("/voice", data=data)


def test_initial_callback_returns_greeting_and_menu(voice_db):
    response = post()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<?xml" in response.text
    assert "<Response>" in response.text
    assert "Muraho" in response.text
    assert "<GetDigits" in response.text
    assert "usobanure ikibazo" in response.text
    assert "inama ku cyonnyi" in response.text
    assert "ibyihutirwa" in response.text


def test_menu_to_record_flow(voice_db):
    post()
    district = post(dtmfDigits="1")
    sector = post(dtmfDigits="1")
    record = post(dtmfDigits="1")

    assert "Gasabo" in district.text
    assert "Kacyiru" in sector.text
    assert "<Record" in record.text
    assert 'action="http://testserver/voice"' in record.text
    assert "Vuga muri make" in record.text


def test_pest_menu_creates_report(voice_db):
    post()
    post(dtmfDigits="2")
    post(dtmfDigits="1")
    post(dtmfDigits="1")
    result = post(dtmfDigits="4")

    assert "<Say>" in result.text
    assert "Kura ibihingwa" in result.text or "Kura" in result.text
    assert "<Hangup" in result.text

    reports = storage.list_recent_diagnoses()
    assert len(reports) == 1
    assert reports[0]["pest_id"] == "bean_fly"
    assert reports[0]["reporter_hash"] == storage.hash_identifier(PHONE)
    assert PHONE not in repr(reports)


def test_alerts_menu_reads_active_alert(voice_db):
    for _ in range(3):
        storage.save_diagnosis(
            reporter_hash=storage.hash_identifier("other-farmer"),
            pest_id="fall_armyworm",
            sector="Kacyiru",
            district="Gasabo",
        )
    alert_service.check_outbreak("fall_armyworm", "Kacyiru", "Gasabo")
    reports_before = len(storage.list_recent_diagnoses())

    post()
    post(dtmfDigits="3")
    post(dtmfDigits="1")
    result = post(dtmfDigits="1")

    assert "<Say>" in result.text
    assert "Ibyihutirwa" in result.text
    assert "<Hangup" in result.text
    assert len(storage.list_recent_diagnoses()) == reports_before


def test_recording_is_transcribed_and_diagnosed(voice_db, monkeypatch, caplog):
    calls: dict = {}

    def fake_download(url):
        calls["url"] = url
        return b"fake-wav-bytes", "recording.wav", "audio/wav"

    def fake_transcribe(audio, **kwargs):
        calls["audio"] = audio
        calls["kwargs"] = kwargs
        return "amababi y'ibigori arashye kandi afite uduhumbi"

    monkeypatch.setattr(voice, "download_recording", fake_download)
    monkeypatch.setattr(asr, "transcribe", fake_transcribe)

    post()
    post(dtmfDigits="1")
    post(dtmfDigits="1")
    post(dtmfDigits="1")

    with caplog.at_level(logging.INFO):
        result = post(recordingUrl=RECORDING_URL)

    assert calls["url"] == RECORDING_URL
    assert calls["audio"] == b"fake-wav-bytes"
    assert calls["kwargs"]["filename"] == "recording.wav"
    assert "<Say>" in result.text
    assert "Inyo y'ibigori" in result.text
    assert "<Hangup" in result.text

    reports = storage.list_recent_diagnoses()
    assert len(reports) == 1
    assert reports[0]["pest_id"] == "fall_armyworm"
    assert reports[0]["reporter_hash"] == storage.hash_identifier(PHONE)
    assert PHONE not in caplog.text
    assert RECORDING_URL not in caplog.text


def test_empty_transcription_asks_farmer_to_repeat(voice_db, monkeypatch):
    monkeypatch.setattr(
        voice,
        "download_recording",
        lambda url: (b"silent", "recording.wav", "audio/wav"),
    )
    monkeypatch.setattr(asr, "transcribe", lambda *args, **kwargs: "")

    post()
    post(dtmfDigits="1")
    post(dtmfDigits="1")
    post(dtmfDigits="1")
    result = post(recordingUrl=RECORDING_URL)

    assert "Ntabwo numvise amajwi neza" in result.text
    assert "<Record" in result.text
    assert "<Hangup" not in result.text
    assert storage.list_recent_diagnoses() == []


def test_three_recordings_trigger_outbreak(voice_db, monkeypatch, caplog):
    monkeypatch.setattr(
        voice,
        "download_recording",
        lambda url: (b"audio", "recording.wav", "audio/wav"),
    )
    monkeypatch.setattr(
        asr,
        "transcribe",
        lambda *args, **kwargs: "amababi y'ibigori arashye kandi afite uduhumbi",
    )

    with caplog.at_level(logging.WARNING):
        for index in range(3):
            session = f"caller-{index}"
            post(session)
            post(session, dtmfDigits="1")
            post(session, dtmfDigits="1")
            post(session, dtmfDigits="1")
            result = post(session, recordingUrl=f"{RECORDING_URL}?n={index}")

    assert "<Say>" in result.text
    assert len(storage.list_recent_diagnoses()) == 3
    alerts = storage.list_alerts()
    assert len(alerts) == 1
    assert alerts[0]["sector"] == "Kacyiru"
    assert "DRY-RUN" in caplog.text
    assert PHONE not in caplog.text


def test_inactive_call_returns_empty_response(voice_db):
    post()
    result = post(isActive="0")

    assert result.status_code == 200
    assert "<Response" in result.text
    assert webhooks.get_session(webhooks.hashed_key("voice-1", PHONE)).stage == "start"


def test_voice_uses_play_when_tts_audio_available(voice_db, monkeypatch):
    monkeypatch.setattr(config, "TTS_BACKEND", "sunbird")
    monkeypatch.setattr(
        tts,
        "synthesize",
        lambda text, **kwargs: tts.SynthesizedAudio(b"fake-wav", "audio/wav"),
    )

    post()
    post(dtmfDigits="2")
    post(dtmfDigits="1")
    post(dtmfDigits="1")
    result = post(dtmfDigits="4")

    assert "<Play" in result.text
    assert 'url="http://testserver/tts/audio/' in result.text
    assert "<Say>" not in result.text
    assert "<Hangup" in result.text
