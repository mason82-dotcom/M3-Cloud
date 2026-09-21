from app.config import Settings
from app.dji.pilot import build_pilot_bootstrap


def test_pilot_bootstrap_fails_closed_when_required_values_are_missing():
    settings = Settings(_env_file=None)

    result = build_pilot_bootstrap(
        settings,
        public_base_url="http://m3-cloud.local",
    )

    assert result["ready"] is False
    assert "app_id" in result["missing"]
    assert "workspace_id" in result["missing"]
    assert "mqtt_url" in result["missing"]
    assert "ws_url" in result["missing"]
    assert result["components"]["media"] is False
    assert result["components"]["mission"] is False


def test_pilot_bootstrap_uses_rc_reachable_urls_and_valid_workspace_uuid():
    settings = Settings(_env_file=None).model_copy(
        update={
            "dji_pilot_app_id": "app-id",
            "dji_pilot_app_key": "app-key",
            "dji_pilot_license": "license",
            "dji_pilot_workspace_id": "e3dea0f5-37f2-4d79-ae58-490af3228069",
            "dji_pilot_api_token": "pilot-token",
            "dji_pilot_mqtt_url": "tcp://192.168.178.45:1883",
            "dji_pilot_mqtt_username": "pilot2",
            "dji_pilot_mqtt_password": "secret",
            "dji_pilot_ws_url": "ws://192.168.178.45:8080/ws/dji-pilot",
            "dji_mqtt_enabled": True,
            "dji_pilot_storage_endpoint": "https://s3.example.test",
            "dji_pilot_storage_provider": "aws",
            "dji_pilot_storage_sts_mode": "federation_token",
        }
    )

    result = build_pilot_bootstrap(
        settings,
        public_base_url="http://192.168.178.45:8080",
    )

    assert result["ready"] is True
    assert result["missing"] == []
    assert result["invalid"] == []
    assert result["api"]["host"] == "http://192.168.178.45:8080"
    assert result["thing"]["host"] == "tcp://192.168.178.45:1883"
    assert result["ws"] == {
        "host": "ws://192.168.178.45:8080/ws/dji-pilot",
        "token": "pilot-token",
    }
    assert result["workspace"]["id"] == "e3dea0f5-37f2-4d79-ae58-490af3228069"
    assert result["components"]["thing"] is True
    assert result["components"]["ws"] is True
    assert result["components"]["map"] is True
    assert result["map"] == {
        "user_name": "M3-Cloud",
        "element_pre_name": "M3CLOUD",
    }
    assert result["components"]["tsa"] is True
    assert result["components"]["mission"] is True
    assert result["components"]["liveshare"] is True


def test_pilot_bootstrap_rejects_invalid_workspace_mqtt_and_ws_scheme():
    settings = Settings(_env_file=None).model_copy(
        update={
            "dji_pilot_app_id": "app-id",
            "dji_pilot_app_key": "app-key",
            "dji_pilot_license": "license",
            "dji_pilot_workspace_id": "not-a-uuid",
            "dji_pilot_api_token": "pilot-token",
            "dji_pilot_mqtt_url": "http://broker",
            "dji_pilot_mqtt_username": "pilot2",
            "dji_pilot_mqtt_password": "secret",
            "dji_pilot_ws_url": "http://not-a-websocket",
        }
    )

    result = build_pilot_bootstrap(
        settings,
        public_base_url="http://m3-cloud.local",
    )

    assert result["ready"] is False
    assert "workspace_id" in result["invalid"]
    assert "mqtt_url" in result["invalid"]
    assert "ws_url" in result["invalid"]


def test_pilot_bootstrap_requires_server_side_dji_mqtt_core():
    value = Settings(_env_file=None).model_copy(
        update={
            "dji_pilot_app_id": "app-id",
            "dji_pilot_app_key": "app-key",
            "dji_pilot_license": "license",
            "dji_pilot_workspace_id": "e3dea0f5-37f2-4d79-ae58-490af3228069",
            "dji_pilot_api_token": "pilot-token",
            "dji_pilot_mqtt_url": "tcp://192.168.178.45:1883",
            "dji_pilot_mqtt_username": "pilot2",
            "dji_pilot_mqtt_password": "secret",
            "dji_pilot_ws_url": "ws://192.168.178.45:8080/ws/dji-pilot",
            "dji_mqtt_enabled": False,
        }
    )

    result = build_pilot_bootstrap(
        value,
        public_base_url="http://192.168.178.45:8080",
    )

    assert result["ready"] is False
    assert "dji_mqtt_enabled" in result["invalid"]


def test_pilot_bootstrap_keeps_media_but_disables_mission_for_minio():
    value = Settings(_env_file=None).model_copy(
        update={
            "dji_pilot_app_id": "app-id",
            "dji_pilot_app_key": "app-key",
            "dji_pilot_license": "license",
            "dji_pilot_workspace_id": "e3dea0f5-37f2-4d79-ae58-490af3228069",
            "dji_pilot_api_token": "pilot-token",
            "dji_pilot_mqtt_url": "tcp://192.168.178.45:1883",
            "dji_pilot_mqtt_username": "pilot2",
            "dji_pilot_mqtt_password": "secret",
            "dji_pilot_ws_url": "ws://192.168.178.45:8080/ws/dji-pilot",
            "dji_mqtt_enabled": True,
            "dji_pilot_storage_endpoint": "http://192.168.178.45:8333",
            "dji_pilot_storage_provider": "minio",
            "dji_pilot_storage_sts_mode": "federation_token",
        }
    )

    result = build_pilot_bootstrap(
        value,
        public_base_url="http://192.168.178.45:8080",
    )

    assert result["ready"] is True
    assert result["components"]["media"] is True
    assert result["components"]["mission"] is False
