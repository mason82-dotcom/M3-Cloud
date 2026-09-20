import json

import pytest

from app.dji.protocol import PropertyMessage
from app.dji.telemetry import TelemetryStore, deep_merge, normalize_telemetry
from app.dji.topics import TopicKind


def test_deep_merge_preserves_partial_state() -> None:
    merged = deep_merge(
        {
            "battery": {"capacity_percent": 80, "remain_flight_time": 600},
            "mode_code": 3,
        },
        {
            "battery": {"capacity_percent": 79},
            "home_latitude": 49.1,
        },
    )

    assert merged["battery"] == {
        "capacity_percent": 79,
        "remain_flight_time": 600,
    }
    assert merged["mode_code"] == 3
    assert merged["home_latitude"] == 49.1


def test_m3_telemetry_keeps_altitude_references_separate() -> None:
    state = normalize_telemetry(
        {
            "latitude": 49.123,
            "longitude": 8.456,
            "elevation": 42.5,
            "height": 153.8,
            "horizontal_speed": 6.2,
            "vertical_speed": -0.4,
            "attitude_head": 127,
            "attitude_roll": 1.2,
            "attitude_pitch": -3.4,
        },
        source_sn="M3E123",
        gateway_sn="RC123",
        source_timestamp_ms=1000,
        received_at_ms=1100,
    )

    assert state["relative_altitude_m"] == 42.5
    assert state["ellipsoid_height_m"] == 153.8
    assert state["attitude"] == {
        "yaw_deg": 127,
        "roll_deg": 1.2,
        "pitch_deg": -3.4,
    }


def test_position_state_is_convergence_not_rtk_fix() -> None:
    state = normalize_telemetry(
        {
            "position_state": {
                "is_fixed": 2,
                "quality": 5,
                "gps_number": 21,
                "rtk_number": 31,
            }
        },
        source_sn="M3T123",
        gateway_sn="RC123",
        source_timestamp_ms=1000,
        received_at_ms=1100,
    )

    assert state["position_state"] == {
        "code": 2,
        "convergence": "CONVERGED",
        "quality": 5,
        "gps_satellites": 21,
        "rtk_satellites": 31,
    }
    assert "fix" not in state["position_state"]


def test_camera_and_battery_normalization() -> None:
    state = normalize_telemetry(
        {
            "battery": {
                "capacity_percent": 67,
                "remain_flight_time": 540,
                "return_home_power": 24,
                "landing_power": 12,
                "batteries": [
                    {
                        "index": 0,
                        "sn": "BAT123",
                        "capacity_percent": 67,
                        "voltage": 15200,
                        "loop_times": 41,
                    }
                ],
            },
            "cameras": [
                {
                    "payload_index": "67-0-0",
                    "camera_mode": 0,
                    "photo_state": 1,
                    "recording_state": 0,
                    "zoom_factor": 7.0,
                    "ir_zoom_factor": 4.0,
                    "ir_metering_mode": 1,
                    "ir_metering_point": {
                        "x": 0.5,
                        "y": 0.4,
                        "temperature": 51.2,
                    },
                }
            ],
        },
        source_sn="M3T123",
        gateway_sn="RC123",
        source_timestamp_ms=1000,
        received_at_ms=1100,
    )

    assert state["battery"]["capacity_percent"] == 67
    assert state["battery"]["remain_flight_time_s"] == 540
    assert state["cameras"][0]["payload_index"] == "67-0-0"
    assert state["cameras"][0]["ir_metering_point"]["temperature"] == 51.2



class FakeRedis:
    def __init__(self):
        self.values = {}
        self.published = []

    async def set(self, key, value, ex=None):
        del ex
        self.values[key] = value
        return True

    async def mget(self, *keys):
        return [self.values.get(key) for key in keys]

    async def publish(self, channel, payload):
        self.published.append((channel, payload))
        return 1


@pytest.mark.asyncio
async def test_telemetry_update_publishes_live_event() -> None:
    redis = FakeRedis()
    store = TelemetryStore(redis)

    state = await store.update(
        source_sn="M3E123",
        kind=TopicKind.OSD,
        message=PropertyMessage(
            tid="t",
            bid="b",
            timestamp=1000,
            gateway="RC123",
            from_sn="M3E123",
            data={
                "latitude": 49.1,
                "longitude": 8.5,
                "elevation": 12.0,
            },
        ),
    )

    assert state["source_sn"] == "M3E123"
    assert len(redis.published) == 1

    channel, raw = redis.published[0]
    event = json.loads(raw)
    assert channel == "m3:live"
    assert event["type"] == "telemetry"
    assert event["device_sn"] == "M3E123"
    assert event["state"]["relative_altitude_m"] == 12.0
