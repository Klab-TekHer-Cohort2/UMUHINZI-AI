"""Tests for the ASR abstraction and the Sunbird backend (API call mocked)."""

from __future__ import annotations

import logging

import pytest
import requests
from fastapi.testclient import TestClient

from app import config
from app.i18n import rw
from app.main import app
from app.services import asr

client = TestClient(app)

# Obviously fake token, only used inside this test file.
FAKE_TOKEN = "test-token-not-a-real-secret"


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, payload: dict | None = None, status_code: int = 200):
        self._payload = payload or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}", response=self
            )

    def json(self) -> dict:
        return self._payload


def test_sunbird_success_sends_expected_request(monkeypatch):
    captured: dict = {}

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        captured.update(
            url=url, headers=headers, files=files, data=data, timeout=timeout
        )
        return FakeResponse(
            {"audio_transcription": "amababi y'ibigori arashye", "language": "kin"}
        )

    monkeypatch.setattr(asr.requests, "post", fake_post)

    backend = asr.SunbirdASR(
        token=FAKE_TOKEN,
        url="https://example.test/tasks/audio/transcriptions",
        timeout=7,
    )
    text = backend.transcribe(
        b"fake-wav-bytes", filename="call.wav", content_type="audio/wav"
    )

    assert text == "amababi y'ibigori arashye"
    assert captured["url"] == "https://example.test/tasks/audio/transcriptions"
    assert captured["headers"] == {"Authorization": f"Bearer {FAKE_TOKEN}"}
    assert captured["data"] == {"language": "kin"}
    assert captured["timeout"] == 7

    filename, payload, content_type = captured["files"]["audio"]
    assert filename == "audio.wav"
    assert payload == b"fake-wav-bytes"
    assert content_type == "audio/wav"


def test_sunbird_accepts_text_field_for_compatibility(monkeypatch):
    monkeypatch.setattr(
        asr.requests,
        "post",
        lambda *args, **kwargs: FakeResponse({"text": "ubushyuhe ku birayi"}),
    )
    backend = asr.SunbirdASR(token=FAKE_TOKEN)
    assert backend.transcribe(b"x", filename="call.mp3") == "ubushyuhe ku birayi"


def test_sunbird_expired_token_raises_clear_error(monkeypatch):
    monkeypatch.setattr(
        asr.requests,
        "post",
        lambda *args, **kwargs: FakeResponse({"detail": "Unauthorized"}, 401),
    )
    backend = asr.SunbirdASR(token=FAKE_TOKEN)

    with pytest.raises(asr.ASRError, match="invalid or expired"):
        backend.transcribe(b"x", filename="call.wav")


def test_sunbird_timeout_raises_clear_error(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.Timeout("slow network")

    monkeypatch.setattr(asr.requests, "post", fake_post)
    backend = asr.SunbirdASR(token=FAKE_TOKEN)

    with pytest.raises(asr.ASRError, match="timed out"):
        backend.transcribe(b"x", filename="call.wav")


def test_missing_token_raises_clear_error():
    backend = asr.SunbirdASR(token="")
    with pytest.raises(asr.ASRError, match="SUNBIRD_API_TOKEN is not set"):
        backend.transcribe(b"x", filename="call.wav")


def test_dispatcher_falls_back_to_mock(monkeypatch, caplog):
    def broken_sunbird(self, *args, **kwargs):
        raise asr.ASRError("Sunbird token is invalid or expired")

    monkeypatch.setattr(config, "ASR_BACKEND", "sunbird")
    monkeypatch.setattr(asr.SunbirdASR, "transcribe", broken_sunbird)
    monkeypatch.setattr(
        asr.MockASR, "transcribe", lambda self, *args, **kwargs: "mock fallback"
    )

    with caplog.at_level(logging.WARNING):
        result = asr.transcribe(b"audio", filename="call.wav")

    assert result == "mock fallback"
    assert "Falling back to mock ASR" in caplog.text
    assert FAKE_TOKEN not in caplog.text


def test_mock_backend_accepts_text_and_returns_empty_for_audio(monkeypatch):
    monkeypatch.delenv("MOCK_ASR_TEXT", raising=False)
    backend = asr.MockASR()

    assert backend.transcribe("amababi y'ibigori") == "amababi y'ibigori"
    assert backend.transcribe(b"real-audio-bytes") == ""


def test_asr_endpoint_transcribes_and_diagnoses(monkeypatch):
    monkeypatch.setattr(
        asr,
        "transcribe",
        lambda *args, **kwargs: "amababi y'ibigori arashye kandi afite uduhumbi",
    )

    response = client.post(
        "/asr",
        files={"audio": ("call.wav", b"fake-audio", "audio/wav")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transcription"].startswith("amababi")
    assert body["diagnosis"]["pest_id"] == "fall_armyworm"
    assert "Twahisemo" in body["reply_rw"]


def test_asr_endpoint_asks_to_repeat_when_empty(monkeypatch):
    monkeypatch.setattr(asr, "transcribe", lambda *args, **kwargs: "")

    response = client.post(
        "/asr",
        files={"audio": ("call.wav", b"fake-audio", "audio/wav")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transcription"] == ""
    assert body["diagnosis"] is None
    assert body["reply_rw"] == rw.ASR_REPEAT_REPLY


def test_asr_endpoint_rejects_empty_upload():
    response = client.post(
        "/asr",
        files={"audio": ("empty.wav", b"", "audio/wav")},
    )
    assert response.status_code == 400


def test_health_reports_asr_backend_without_token():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["asr_backend"] in {"mock", "sunbird"}
    assert isinstance(body["sunbird_configured"], bool)
    assert "token" not in " ".join(body.keys()).lower()
