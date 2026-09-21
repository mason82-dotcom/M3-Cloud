from __future__ import annotations

import time
from typing import Any, Mapping


def device_model(record: Mapping[str, Any]) -> dict[str, str]:
    role = str(record.get("role") or "")
    domain = record.get("domain")
    if domain is None:
        domain = "2" if role == "gateway" else "0"

    product_type = record.get("type")
    sub_type = record.get("sub_type")
    type_text = str(product_type if product_type is not None else 0)
    subtype_text = str(sub_type if sub_type is not None else 0)
    domain_text = str(domain)
    return {
        "key": f"{domain_text}-{type_text}-{subtype_text}",
        "domain": domain_text,
        "type": type_text,
        "sub_type": subtype_text,
    }


def topology_device(record: Mapping[str, Any]) -> dict[str, Any]:
    model = str(record.get("model") or "DJI")
    return {
        "sn": str(record.get("sn") or ""),
        "device_model": device_model(record),
        "online_status": bool(record.get("online")),
        "device_callsign": model,
        "user_id": "",
        "user_callsign": "",
        "icon_urls": {},
    }


def build_topologies(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gateways = {
        str(item.get("sn")): item
        for item in devices
        if item.get("role") == "gateway" and item.get("sn")
    }
    aircraft_by_gateway: dict[str, list[dict[str, Any]]] = {}
    for item in devices:
        if item.get("role") != "aircraft":
            continue
        gateway_sn = item.get("gateway_sn")
        if not isinstance(gateway_sn, str) or not gateway_sn:
            continue
        aircraft_by_gateway.setdefault(gateway_sn, []).append(item)

    result: list[dict[str, Any]] = []
    for gateway_sn in sorted(gateways):
        hosts = sorted(
            aircraft_by_gateway.get(gateway_sn, []),
            key=lambda item: str(item.get("sn") or ""),
        )
        result.append(
            {
                "hosts": [topology_device(item) for item in hosts],
                "parents": [topology_device(gateways[gateway_sn])],
            }
        )
    return result


def pilot_ws_message(
    biz_code: str,
    data: Mapping[str, Any] | None = None,
    *,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    return {
        "biz_code": biz_code,
        "version": "1.0",
        "timestamp": (
            timestamp_ms
            if timestamp_ms is not None
            else int(time.time() * 1000)
        ),
        "data": dict(data or {}),
    }


def telemetry_to_device_osd(event: Mapping[str, Any]) -> dict[str, Any] | None:
    if event.get("type") != "telemetry":
        return None

    state = event.get("state")
    if not isinstance(state, Mapping):
        return None

    sn = event.get("device_sn") or state.get("source_sn")
    if not isinstance(sn, str) or not sn:
        return None

    attitude = state.get("attitude")
    attitude_head = attitude.get("yaw_deg") if isinstance(attitude, Mapping) else None

    mapping = {
        "latitude": state.get("latitude"),
        "longitude": state.get("longitude"),
        "height": state.get("ellipsoid_height_m"),
        "attitude_head": attitude_head,
        "elevation": state.get("relative_altitude_m"),
        "horizontal_speed": state.get("horizontal_speed_mps"),
        "vertical_speed": state.get("vertical_speed_mps"),
    }
    host = {
        key: value
        for key, value in mapping.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    if "latitude" not in host or "longitude" not in host:
        return None

    timestamp = event.get("timestamp")
    return pilot_ws_message(
        "device_osd",
        {"host": host, "sn": sn},
        timestamp_ms=timestamp if isinstance(timestamp, int) and not isinstance(timestamp, bool) else None,
    )


def live_event_to_pilot(event: Mapping[str, Any]) -> dict[str, Any] | None:
    event_type = event.get("type")
    if event_type == "telemetry":
        return telemetry_to_device_osd(event)
    if event_type == "device_online":
        return pilot_ws_message("device_online")
    if event_type == "device_offline":
        return pilot_ws_message("device_offline")
    if event_type == "topology":
        return pilot_ws_message("device_update_topo")
    return None
