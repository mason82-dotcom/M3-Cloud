from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_liveness() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_root_identifies_service() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["service"] == "m3-cloud"
