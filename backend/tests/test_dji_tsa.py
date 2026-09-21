from types import SimpleNamespace

from starlette.datastructures import QueryParams

from app.api_dji_tsa import _websocket_token
from app.dji.tsa import build_topologies, live_event_to_pilot


def test_topology_groups_m3_aircraft_under_rc_pro():
    devices = [
        {
            "sn": "RC123",
            "role": "gateway",
            "domain": "2",
            "type": 144,
            "sub_type": 0,
            "model": "DJI_RC_PRO_ENTERPRISE",
            "online": True,
            "gateway_sn": "RC123",
        },
        {
            "sn": "M3T123",
            "role": "aircraft",
            "domain": "0",
            "type": 77,
            "sub_type": 1,
            "model": "DJI_MAVIC_3T",
            "online": True,
            "gateway_sn": "RC123",
        },
    ]

    value = build_topologies(devices)

    assert len(value) == 1
    assert value[0]["parents"][0]["device_model"]["key"] == "2-144-0"
    assert value[0]["hosts"][0]["device_model"]["key"] == "0-77-1"
    assert value[0]["hosts"][0]["sn"] == "M3T123"


def test_dji_telemetry_translates_to_device_osd():
    message = live_event_to_pilot(
        {
            "type": "telemetry",
            "device_sn": "M3E123",
            "timestamp": 123456,
            "state": {
                "latitude": 49.1,
                "longitude": 8.4,
                "ellipsoid_height_m": 142.5,
                "relative_altitude_m": 50.0,
                "horizontal_speed_mps": 7.2,
                "vertical_speed_mps": -0.2,
                "attitude": {"yaw_deg": 91.0},
            },
        }
    )

    assert message == {
        "biz_code": "device_osd",
        "version": "1.0",
        "timestamp": 123456,
        "data": {
            "host": {
                "latitude": 49.1,
                "longitude": 8.4,
                "height": 142.5,
                "attitude_head": 91.0,
                "elevation": 50.0,
                "horizontal_speed": 7.2,
                "vertical_speed": -0.2,
            },
            "sn": "M3E123",
        },
    }


def test_lyrebird_vehicle_telemetry_is_not_forwarded_to_pilot_tsa():
    assert (
        live_event_to_pilot(
            {
                "type": "vehicle_telemetry",
                "state": {"latitude": 49.1, "longitude": 8.4},
            }
        )
        is None
    )


def test_topology_transitions_use_dji_biz_codes():
    assert live_event_to_pilot({"type": "device_online"})["biz_code"] == "device_online"
    assert live_event_to_pilot({"type": "device_offline"})["biz_code"] == "device_offline"
    assert live_event_to_pilot({"type": "topology"})["biz_code"] == "device_update_topo"



def test_websocket_token_accepts_dji_case_variants():
    lower = SimpleNamespace(query_params=QueryParams("x-auth-token=abc"))
    mixed = SimpleNamespace(query_params=QueryParams("x-Auth-token=def"))
    upper = SimpleNamespace(query_params=QueryParams("X-AUTH-TOKEN=ghi"))

    assert _websocket_token(lower) == "abc"
    assert _websocket_token(mixed) == "def"
    assert _websocket_token(upper) == "ghi"
