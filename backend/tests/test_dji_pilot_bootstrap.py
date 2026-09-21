from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


client = TestClient(app)


def _configure(monkeypatch):
    monkeypatch.setattr(settings, "dji_pilot_enabled", True)
    monkeypatch.setattr(settings, "dji_pilot_bootstrap_token", "bootstrap-secret")
    monkeypatch.setattr(settings, "dji_pilot_app_id", "app-id")
    monkeypatch.setattr(settings, "dji_pilot_app_key", "app-key")
    monkeypatch.setattr(settings, "dji_pilot_license", "app-license")
    monkeypatch.setattr(
        settings,
        "dji_pilot_workspace_id",
        "57a21ed4-2aa3-4a5c-88da-e4afcab640c7",
    )
    monkeypatch.setattr(settings, "dji_pilot_platform_name", "M3-Cloud")
    monkeypatch.setattr(settings, "dji_pilot_workspace_name", "Field Ops")
    monkeypatch.setattr(settings, "dji_pilot_workspace_desc", "RC Pro Enterprise")
    monkeypatch.setattr(settings, "dji_pilot_api_token", "pilot-api-token")
    monkeypatch.setattr(settings, "dji_pilot_api_url", "http://m3-cloud.local:8080")
    monkeypatch.setattr(settings, "dji_pilot_mqtt_url", "tcp://m3-cloud.local:1883")
    monkeypatch.setattr(settings, "dji_pilot_mqtt_username", "pilot2")
    monkeypatch.setattr(settings, "dji_pilot_mqtt_password", "secret")
    monkeypatch.setattr(
        settings,
        "dji_pilot_ws_url",
        "ws://m3-cloud.local:8080/ws/dji-pilot",
    )
    monkeypatch.setattr(settings, "dji_mqtt_enabled", True)


def test_pilot_bootstrap_is_fail_closed(monkeypatch):
    _configure(monkeypatch)

    response = client.post("/api/v1/dji/pilot/bootstrap")

    assert response.status_code == 401


def test_pilot_bootstrap_returns_full_implemented_capabilities(monkeypatch):
    _configure(monkeypatch)

    response = client.post(
        "/api/v1/dji/pilot/bootstrap",
        headers={"X-M3-Pilot-Bootstrap": "bootstrap-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["license"] == {
        "app_id": "app-id",
        "app_key": "app-key",
        "license": "app-license",
    }
    assert body["thing"]["host"] == "tcp://m3-cloud.local:1883"
    assert body["workspace"]["id"] == "57a21ed4-2aa3-4a5c-88da-e4afcab640c7"
    assert body["api"]["token"] == "pilot-api-token"
    assert body["ws"]["host"] == "ws://m3-cloud.local:8080/ws/dji-pilot"
    assert body["components"]["thing"] is True
    assert body["components"]["api"] is True
    assert body["components"]["ws"] is True
    assert body["components"]["map"] is True
    assert body["components"]["tsa"] is True
    assert body["components"]["liveshare"] is True


def test_legacy_unauthenticated_get_bootstrap_is_gone(monkeypatch):
    _configure(monkeypatch)

    response = client.get("/api/v1/dji/pilot/bootstrap")

    assert response.status_code == 405


def test_pilot_bootstrap_rejects_invalid_mqtt_scheme(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "dji_pilot_mqtt_url", "mqtt://m3-cloud.local:1883")

    response = client.post(
        "/api/v1/dji/pilot/bootstrap",
        headers={"X-M3-Pilot-Bootstrap": "bootstrap-secret"},
    )

    assert response.status_code == 503
    assert "invalid:mqtt_url" in response.json()["detail"]


def test_pilot_bootstrap_is_not_cacheable(monkeypatch):
    _configure(monkeypatch)

    response = client.post(
        "/api/v1/dji/pilot/bootstrap",
        headers={"X-M3-Pilot-Bootstrap": "bootstrap-secret"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"


def test_pilot_status_never_exposes_secrets(monkeypatch):
    _configure(monkeypatch)

    response = client.get("/api/v1/dji/pilot/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    serialized = response.text
    assert "bootstrap-secret" not in serialized
    assert "pilot-api-token" not in serialized
    assert "app-key" not in serialized
    assert "app-license" not in serialized
    assert body["components"]["thing"] is True
