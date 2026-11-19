"""Tests for text-to-speech backends, /tts and the cached Play audio endpoint."""

import logging

import pytest
import requests
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import tts

client = TestClient(app)
FAKE_TOKEN = "test-token-not-a-real-secret"

# Obviously fake audio bytes; no real encoding is needed for these tests.
FAKE_AUDIO = b"RIFF-fake-wav-bytes"


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(
        self,
        content: bytes = b"",
        headers: dict | None = None,
        payload: dict | None = None,
        status_code: int = 200,
    ):
        self.content = content
        self.headers = headers or {}
        self._payload = payload or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}", response=self
            )

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def tts_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TTS_BACKEND", "mock")
    monkeypatch.setattr(config, "SUNBIRD_API_TOKEN", "")
    monkeypatch.setattr(config, "SUNBIRD_TTS_URL", "https://example.test/tts")
    monkeypatch.setattr(config, "SUNBIRD_TTS_VOICE", "")
    monkeypatch.setattr(config, "SUNBIRD_TIMEOUT_SECONDS", 7)
    tts.clear_cache()
    yield
    tts.clear_cache()


def test_mock_backend_returns_no_audio():
    result = tts.MockTTS().synthesize("Muraho")

    assert result.data == b""
    assert result.content_type == "audio/wav"


def test_sunbird_stream_request_and_audio(tts_setup, monkeypatch, caplog):
    captured: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return FakeResponse(FAKE_AUDIO, {"Content-Type": "audio/wav"})

    monkeypatch.setattr(tts.requests, "post", fake_post)

    backend = tts.SunbirdTTS(
        token=FAKE_TOKEN,
        url="https://example.test/tasks/audio/speech",
        timeout=7,
        voice="TestVoice",
    )

    with caplog.at_level(logging.WARNING):
        audio = backend.synthesize("Muraho", language="kin")

    assert audio.data == FAKE_AUDIO
    assert audio.content_type == "audio/wav"
    assert captured["url"] == "https://example.test/tasks/audio/speech"
    assert captured["headers"] == {"Authorization": f"Bearer {FAKE_TOKEN}"}
    assert captured["json"] == {
        "text": "Muraho",
        "language": "kin",
        "response_mode": "stream",
        "voice": "TestVoice",
    }
    assert captured["timeout"] == 7
    assert FAKE_TOKEN not in caplog.text


def test_sunbird_downloads_signed_audio_url(tts_setup, monkeypatch):
    signed = "storage.example.test/tts/abc.wav?sig=secret"
    captured: dict = {}

    monkeypatch.setattr(
        tts.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(
            content=b'{"audio_url": "' + signed.encode() + b'"}',
            headers={"Content-Type": "application/json"},
            payload={"audio_url": signed},
        ),
    )

    def fake_get(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return FakeResponse(FAKE_AUDIO, {"Content-Type": "audio/mpeg"})

    monkeypatch.setattr(tts.requests, "get", fake_get)

    audio = tts.SunbirdTTS(token=FAKE_TOKEN).synthesize("Muraho")

    assert audio.data == FAKE_AUDIO
    assert audio.content_type == "audio/mpeg"
    assert captured["url"] == f"https://{signed}"
    assert captured["timeout"] == 7


def test_missing_token_raises_clear_error(tts_setup):
    with pytest.raises(tts.TTSError, match="SUNBIRD_API_TOKEN is not set"):
        tts.SunbirdTTS(token="").synthesize("Muraho")


def test_expired_token_raises_clear_error(tts_setup, monkeypatch):
    monkeypatch.setattr(
        tts.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(status_code=401),
    )

    with pytest.raises(tts.TTSError, match="invalid or expired"):
        tts.SunbirdTTS(token=FAKE_TOKEN).synthesize("Muraho")


def test_dispatcher_falls_back_to_mock(tts_setup, monkeypatch, caplog):
    def broken_sunbird(self, *args, **kwargs):
        raise tts.TTSError("Sunbird token is invalid or expired")

    monkeypatch.setattr(config, "TTS_BACKEND", "sunbird")
    monkeypatch.setattr(config, "SUNBIRD_API_TOKEN", FAKE_TOKEN)
    monkeypatch.setattr(tts.SunbirdTTS, "synthesize", broken_sunbird)

    with caplog.at_level(logging.WARNING):
        audio = tts.synthesize("Muraho")

    assert audio.data == b""
    assert "Falling back to mock" in caplog.text
    assert FAKE_TOKEN not in caplog.text


def test_tts_endpoint_with_mock_has_no_audio(tts_setup):
    response = client.post("/tts", json={"text": "Muraho"})

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["X-TTS-Backend"] == "mock"
    assert response.headers["X-Audio-Available"] == "0"


def test_tts_endpoint_returns_audio_and_cached_play_url(tts_setup, monkeypatch):
    monkeypatch.setattr(config, "TTS_BACKEND", "sunbird")
    monkeypatch.setattr(
        tts,
        "synthesize",
        lambda text, **kwargs: tts.SynthesizedAudio(FAKE_AUDIO, "audio/mpeg"),
    )

    response = client.post("/tts", json={"text": "Muraho"})

    assert response.status_code == 200
    assert response.content == FAKE_AUDIO
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.headers["X-Audio-Available"] == "1"
    key = response.headers["X-Audio-Key"]
    assert len(key) == 64

    cached = client.get(f"/tts/audio/{key}")
    assert cached.status_code == 200
    assert cached.content == FAKE_AUDIO
    assert cached.headers["content-type"].startswith("audio/mpeg")

    missing = client.get("/tts/audio/not-a-real-key")
    assert missing.status_code == 404


def test_tts_endpoint_rejects_empty_text(tts_setup):
    response = client.post("/tts", json={"text": ""})
    assert response.status_code == 422


def test_health_reports_tts_backend_without_token(tts_setup):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["tts_backend"] == "mock"
    assert isinstance(body["sunbird_configured"], bool)
    assert "token" not in " ".join(body.keys()).lower()
