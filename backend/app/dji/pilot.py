from __future__ import annotations

from typing import Any
from uuid import UUID

from app.config import Settings


_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("app_id", "dji_pilot_app_id"),
    ("app_key", "dji_pilot_app_key"),
    ("license", "dji_pilot_license"),
    ("workspace_id", "dji_pilot_workspace_id"),
    ("api_token", "dji_pilot_api_token"),
    ("mqtt_url", "dji_pilot_mqtt_url"),
    ("mqtt_username", "dji_pilot_mqtt_username"),
    ("mqtt_password", "dji_pilot_mqtt_password"),
)


def _valid_workspace_id(value: str) -> bool:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return str(parsed) == value.lower()


def build_pilot_bootstrap(
    settings: Settings,
    *,
    public_base_url: str,
) -> dict[str, Any]:
    """Build the DJI Pilot 2 JSBridge configuration without inventing defaults."""

    missing = [
        public_name
        for public_name, setting_name in _REQUIRED_FIELDS
        if not str(getattr(settings, setting_name, "") or "").strip()
    ]

    workspace_id = settings.dji_pilot_workspace_id.strip()
    invalid: list[str] = []
    if workspace_id and not _valid_workspace_id(workspace_id):
        invalid.append("workspace_id")

    mqtt_url = settings.dji_pilot_mqtt_url.strip()
    if mqtt_url and not mqtt_url.startswith(("tcp://", "ws://", "wss://")):
        invalid.append("mqtt_url")

    api_host = settings.dji_pilot_api_url.strip() or public_base_url.rstrip("/")
    if not api_host.startswith(("http://", "https://")):
        invalid.append("api_url")

    ready = not missing and not invalid
    return {
        "ready": ready,
        "missing": missing,
        "invalid": invalid,
        "license": {
            "app_id": settings.dji_pilot_app_id,
            "app_key": settings.dji_pilot_app_key,
            "license": settings.dji_pilot_license,
        },
        "workspace": {
            "id": workspace_id,
            "platform_name": settings.dji_pilot_platform_name,
            "name": settings.dji_pilot_workspace_name,
            "description": settings.dji_pilot_workspace_desc,
        },
        "api": {
            "host": api_host,
            "token": settings.dji_pilot_api_token,
        },
        "thing": {
            "host": mqtt_url,
            "username": settings.dji_pilot_mqtt_username,
            "password": settings.dji_pilot_mqtt_password,
        },
        "liveshare": {
            "video_publish_type": settings.dji_pilot_live_publish_type,
        },
        # Only advertise modules whose server-side protocol surface exists.
        # These flags become true in the Media/Wayline/TSA implementation commits.
        "components": {
            "api": True,
            "thing": True,
            "liveshare": True,
            "ws": False,
            "map": False,
            "tsa": False,
            "media": False,
            "mission": False,
        },
    }
