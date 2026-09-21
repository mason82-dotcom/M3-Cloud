import json

from app.dji.protocol import parse_envelope
from app.dji.registry import model_name, topology_identities


def test_m3_model_mapping() -> None:
    assert model_name(77, 0) == "DJI_MAVIC_3E"
    assert model_name(77, 1) == "DJI_MAVIC_3T"
    # DJI Cloud API currently documents no M3M 77/x identity. Keep 77/2 raw/unverified.
    assert model_name(77, 2) == "DJI_TYPE_77_2"
    assert model_name(77, 3) == "DJI_MAVIC_3TA"
    assert model_name(144, 0) == "DJI_RC_PRO_ENTERPRISE"


def test_topology_never_retains_device_secret_or_nonce() -> None:
    envelope = parse_envelope(
        {
            "tid": "t",
            "bid": "b",
            "timestamp": 1,
            "method": "update_topo",
            "data": {
                "domain": "2",
                "type": 144,
                "sub_type": 0,
                "device_secret": "gateway-secret",
                "nonce": "gateway-nonce",
                "thing_version": "1.1.2",
                "sub_devices": [
                    {
                        "sn": "M3T123",
                        "domain": "0",
                        "type": 77,
                        "sub_type": 1,
                        "index": "A",
                        "device_secret": "aircraft-secret",
                        "nonce": "aircraft-nonce",
                        "thing_version": "1.1.2",
                    }
                ],
            },
        }
    )

    gateway, children = topology_identities("RC123", envelope)
    serialized = json.dumps([gateway.__dict__, *[child.__dict__ for child in children]])

    assert gateway.model == "DJI_RC_PRO_ENTERPRISE"
    assert children[0].model == "DJI_MAVIC_3T"
    assert "gateway-secret" not in serialized
    assert "aircraft-secret" not in serialized
    assert "nonce" not in serialized
