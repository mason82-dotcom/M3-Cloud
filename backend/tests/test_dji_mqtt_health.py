from types import SimpleNamespace

import pytest

from app.api_operations import _dji_health
from app.config import settings
from app.dji.mqtt import DJIMqttTransport


async def _noop_handler(topic: str, payload: bytes) -> None:
    del topic, payload


def test_dji_mqtt_transport_tracks_connection_state() -> None:
    transport = DJIMqttTransport(_noop_handler, host="127.0.0.1", port=1883)

    assert transport.connected is False

    transport._on_connect(transport.client, None, None, 0, None)
    assert transport.connected is True
    assert transport.last_connection_reason == "0"

    transport._on_disconnect(transport.client, None, None, 7, None)
    assert transport.connected is False
    assert transport.last_connection_reason == "7"


def test_dji_health_reports_actual_mqtt_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dji_mqtt_enabled", True)
    transport = SimpleNamespace(connected=False, last_connection_reason="Not authorized")
    service = SimpleNamespace(transport=transport)

    assert _dji_health(service) == {
        "ok": False,
        "status": "disconnected",
        "connected": False,
        "last_reason": "Not authorized",
    }

    transport.connected = True
    assert _dji_health(service)["status"] == "connected"
    assert _dji_health(service)["ok"] is True


def test_dji_health_reports_disabled_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dji_mqtt_enabled", False)

    assert _dji_health(None) == {
        "ok": False,
        "status": "disabled",
        "connected": False,
    }
