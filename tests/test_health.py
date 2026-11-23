"""Stage 1 smoke tests: the FastAPI app starts and answers its health check."""

from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import asr

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "Umuhinzi AI"


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Do not assert the value: it depends on whether a local `.env` has keys.
    assert isinstance(body["africastalking_configured"], bool)


def test_health_reports_nvidia_status(monkeypatch):
    monkeypatch.setattr(config, "ASR_BACKEND", "nvidia")
    monkeypatch.setattr(config, "ASR_FALLBACK", "mock")
    monkeypatch.setattr(asr, "nemo_is_available", lambda: True)

    body = client.get("/health").json()

    assert body["asr_backend"] == "nvidia"
    assert body["asr_fallback"] == "mock"
    assert body["nemo_available"] is True
