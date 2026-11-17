"""Stage 1 smoke tests: the FastAPI app starts and answers its health check."""

from fastapi.testclient import TestClient

from app.main import app

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
