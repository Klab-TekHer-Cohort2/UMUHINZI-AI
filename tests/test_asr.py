"""Tests for the ASR abstraction and the Sunbird backend (API call mocked)."""

from __future__ import annotations

import io
import logging
import sys
import types
import wave
from pathlib import Path

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


def wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 160)
    return buffer.getvalue()


class FakeNemoModel:
    def __init__(self, result: object):
        self.result = result
        self.calls: list[dict] = []

    def transcribe(self, paths2audio_files):
        self.calls.append({"paths2audio_files": list(paths2audio_files)})
        return self.result


class BrokenNemoModel:
    def transcribe(self, paths2audio_files):
        raise RuntimeError("decoder crashed")


def prime_nemo_cache(monkeypatch, model: object) -> None:
    monkeypatch.setattr(config, "NVIDIA_ASR_MODEL", asr.DEFAULT_NVIDIA_ASR_MODEL)
    monkeypatch.setattr(asr, "_NEMO_MODEL", model)
    monkeypatch.setattr(asr, "_NEMO_MODEL_NAME", asr.DEFAULT_NVIDIA_ASR_MODEL)


def install_fake_nemo_modules(monkeypatch, from_pretrained) -> None:
    nemo = types.ModuleType("nemo")
    nemo.__path__ = []
    collections = types.ModuleType("nemo.collections")
    collections.__path__ = []
    nemo_asr = types.ModuleType("nemo.collections.asr")
    nemo_asr.__path__ = []
    models = types.ModuleType("nemo.collections.asr.models")

    class EncDecRNNTBPEModel:
        @staticmethod
        def from_pretrained(name):
            return from_pretrained(name)

    models.EncDecRNNTBPEModel = EncDecRNNTBPEModel
    nemo_asr.models = models
    collections.asr = nemo_asr
    nemo.collections = collections

    for name, module in {
        "nemo": nemo,
        "nemo.collections": collections,
        "nemo.collections.asr": nemo_asr,
        "nemo.collections.asr.models": models,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


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


def test_nvidia_backend_transcribes_with_mocked_model(monkeypatch):
    model = FakeNemoModel(["  amababi y'ibigori arashye  "])
    prime_nemo_cache(monkeypatch, model)
    monkeypatch.setattr(config, "ASR_BACKEND", "nvidia")

    text = asr.transcribe(
        wav_bytes(), filename="call.wav", content_type="audio/wav"
    )

    assert text == "amababi y'ibigori arashye"
    assert len(model.calls) == 1
    audio_path = Path(model.calls[0]["paths2audio_files"][0])
    assert not audio_path.exists()


def test_nvidia_model_is_loaded_once(monkeypatch):
    loaded: list[str] = []
    model = FakeNemoModel(["isazi ziri ku mizi y'ibishyimbo"])
    install_fake_nemo_modules(
        monkeypatch, lambda name: loaded.append(name) or model
    )
    monkeypatch.setattr(asr, "nemo_is_available", lambda: True)
    monkeypatch.setattr(asr, "_NEMO_MODEL", None)
    monkeypatch.setattr(asr, "_NEMO_MODEL_NAME", None)
    monkeypatch.setattr(config, "ASR_BACKEND", "nvidia")
    monkeypatch.setattr(config, "NVIDIA_ASR_MODEL", asr.DEFAULT_NVIDIA_ASR_MODEL)

    first = asr.transcribe(wav_bytes(), filename="one.wav")
    second = asr.transcribe(wav_bytes(), filename="two.wav")

    assert first == second == "isazi ziri ku mizi y'ibishyimbo"
    assert loaded == [asr.DEFAULT_NVIDIA_ASR_MODEL]
    assert len(model.calls) == 2


def test_nvidia_falls_back_to_sunbird_when_nemo_missing(monkeypatch, caplog):
    monkeypatch.setattr(config, "ASR_BACKEND", "nvidia")
    monkeypatch.setattr(config, "ASR_FALLBACK", "sunbird")
    monkeypatch.setattr(asr, "nemo_is_available", lambda: False)
    monkeypatch.setattr(asr, "_NEMO_MODEL", None)
    monkeypatch.setattr(asr, "_NEMO_MODEL_NAME", None)
    monkeypatch.setattr(
        asr.SunbirdASR,
        "transcribe",
        lambda self, *args, **kwargs: "sunbird fallback",
    )

    with caplog.at_level(logging.WARNING):
        result = asr.transcribe(wav_bytes(), filename="call.wav")

    assert result == "sunbird fallback"
    assert "NeMo is not installed" in caplog.text
    assert "Falling back to sunbird ASR" in caplog.text


def test_nvidia_falls_back_to_sunbird_when_transcription_fails(
    monkeypatch, caplog
):
    prime_nemo_cache(monkeypatch, BrokenNemoModel())
    monkeypatch.setattr(config, "ASR_BACKEND", "nvidia")
    monkeypatch.setattr(config, "ASR_FALLBACK", "sunbird")
    monkeypatch.setattr(
        asr.SunbirdASR,
        "transcribe",
        lambda self, *args, **kwargs: "sunbird fallback",
    )

    with caplog.at_level(logging.WARNING):
        result = asr.transcribe(wav_bytes(), filename="call.wav")

    assert result == "sunbird fallback"
    assert "NeMo ASR failed: decoder crashed" in caplog.text
    assert "Falling back to sunbird ASR" in caplog.text


def test_nvidia_falls_back_to_mock_when_sunbird_fails(monkeypatch, caplog):
    monkeypatch.setattr(config, "ASR_BACKEND", "nvidia")
    monkeypatch.setattr(config, "ASR_FALLBACK", "sunbird")
    monkeypatch.setattr(asr, "nemo_is_available", lambda: False)
    monkeypatch.setattr(asr, "_NEMO_MODEL", None)
    monkeypatch.setattr(asr, "_NEMO_MODEL_NAME", None)

    def broken_sunbird(self, *args, **kwargs):
        raise asr.ASRError("Sunbird token is invalid or expired")

    monkeypatch.setattr(asr.SunbirdASR, "transcribe", broken_sunbird)
    monkeypatch.setattr(
        asr.MockASR, "transcribe", lambda self, *args, **kwargs: "mock fallback"
    )

    with caplog.at_level(logging.WARNING):
        result = asr.transcribe(wav_bytes(), filename="call.wav")

    assert result == "mock fallback"
    assert "Sunbird ASR fallback failed" in caplog.text
    assert "Falling back to mock ASR" in caplog.text


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
    assert body["asr_backend"] in {"mock", "sunbird", "nvidia"}
    assert isinstance(body["nemo_available"], bool)
    assert isinstance(body["sunbird_configured"], bool)
    assert "token" not in " ".join(body.keys()).lower()
