from app.config import settings
from app.vehicles.dji_cloud import _device_online, _updated_at_ms


def device(**updates):
    value = {
        "online": True,
        "updated_at_ms": 100_000,
    }
    value.update(updates)
    return value


def test_dji_cloud_online_requires_fresh_telemetry_after_topology_grace():
    ttl_ms = settings.dji_telemetry_ttl_seconds * 1000

    assert _device_online(
        device(),
        None,
        now_ms=100_000 + ttl_ms - 1,
    ) is True
    assert _device_online(
        device(),
        None,
        now_ms=100_000 + ttl_ms + 1,
    ) is False


def test_dji_cloud_fresh_telemetry_keeps_aircraft_online():
    ttl_ms = settings.dji_telemetry_ttl_seconds * 1000

    assert _device_online(
        device(updated_at_ms=1),
        {"last_seen_ms": 200_000},
        now_ms=200_000 + ttl_ms - 1,
    ) is True


def test_dji_cloud_stale_telemetry_cannot_leave_aircraft_online():
    ttl_ms = settings.dji_telemetry_ttl_seconds * 1000

    assert _device_online(
        device(),
        {"last_seen_ms": 200_000},
        now_ms=200_000 + ttl_ms + 1,
    ) is False


def test_explicit_topology_offline_always_wins():
    assert _device_online(
        device(online=False),
        {"last_seen_ms": 200_000},
        now_ms=200_000,
    ) is False


def test_vehicle_timestamp_tracks_latest_telemetry_not_only_topology():
    assert _updated_at_ms(
        device(updated_at_ms=100_000),
        {
            "last_seen_ms": 120_000,
            "received_at_ms": 119_000,
        },
    ) == 120_000
