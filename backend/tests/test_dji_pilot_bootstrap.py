from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


client = TestClient(app)


def _configure(monkeypatch):
    monkeypatch.setattr(settings, "dji_pilot_enabled", True)
    monkeypatch.setattr(settings, "dji_pilot_bootstrap_token", "bootstrap-secret")
    monkeypatch.setattr(settings, "dji_cloud_app_id", "app-id")
    monkeypatch.setattr(settings, "dji_cloud_app_key", "app-key")
    monkeypatch.setattr(settings, "dji_cloud_app_license", "app-license")
    monkeypatch.setattr(settings, "dji_pilot_mqtt_url", "tcp://m3-cloud.local:1883")
    monkeypatch.setattr(settings, "dji_pilot_mqtt_username", "pilot2")
    monkeypatch.setattr(settings, "dji_pilot_mqtt_password", "secret")
    monkeypatch.setattr(settings, "dji_workspace_id", "57a21ed4-2aa3-4a5c-88da-e4afcab640c7")
    monkeypatch.setattr(settings, "dji_platform_name", "M3-Cloud")
    monkeypatch.setattr(settings, "dji_workspace_name", "Field Ops")
    monkeypatch.setattr(settings, "dji_workspace_description", "RC Pro Enterprise")


def test_pilot_bootstrap_is_fail_closed(monkeypatch):
    _configure(monkeypatch)
    response = client.post("/api/v1/dji/pilot/bootstrap")
    assert response.status_code == 401


def test_pilot_bootstrap_returns_only_implemented_modules(monkeypatch):
    _configure(monkeypatch)
    response = client.post(
        "/api/v1/dji/pilot/bootstrap",
        headers={"X-M3-Pilot-Bootstrap": "bootstrap-secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["license"]["app_id"] == "app-id"
    assert body["mqtt"]["host"] == "tcp://m3-cloud.local:1883"
    assert body["workspace"]["id"] == "57a21ed4-2aa3-4a5c-88da-e4afcab640c7"
    assert body["modules"] == {
        "thing": True,
        "api": False,
        "ws": False,
        "map": False,
        "tsa": False,
        "media": False,
        "mission": False,
        "liveshare": False,
    }


def test_pilot_bootstrap_rejects_non_jsbridge_mqtt_scheme(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "dji_pilot_mqtt_url", "mqtt://m3-cloud.local:1883")
    response = client.post(
        "/api/v1/dji/pilot/bootstrap",
        headers={"X-M3-Pilot-Bootstrap": "bootstrap-secret"},
    )
    assert response.status_code == 503
    assert "tcp:// or ws://" in response.json()["detail"]


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
    monkeypatch.setattr(settings, "dji_mqtt_enabled", True)
    response = client.get("/api/v1/dji/pilot/status")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    serialized = response.text
    assert "bootstrap-secret" not in serialized
    assert "app-key" not in serialized
    assert "app-license" not in serialized
    assert '"thing":true' in serialized
