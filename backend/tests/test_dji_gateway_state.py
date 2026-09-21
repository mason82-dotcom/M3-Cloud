from app.dji.telemetry import normalize_telemetry


def test_gateway_live_capabilities_are_preserved():
    live_capacity = {
        "available_video_number": 2,
        "coexist_video_number_max": 1,
        "device_list": [
            {
                "sn": "M3T123",
                "camera_list": [
                    {
                        "camera_index": "67-0-0",
                        "video_list": [
                            {"video_index": "normal-0"},
                            {"video_index": "thermal-0"},
                        ],
                    }
                ],
            }
        ],
    }
    live_status = [
        {
            "video_id": "M3T123/67-0-0/normal-0",
            "video_type": "normal",
            "video_quality": 3,
        }
    ]

    state = normalize_telemetry(
        {
            "live_capacity": live_capacity,
            "live_status": live_status,
            "is_cloud_control_auth": True,
        },
        source_sn="RC123",
        gateway_sn="RC123",
        source_timestamp_ms=1000,
        received_at_ms=1100,
    )

    assert state["live_capacity"] == live_capacity
    assert state["live_status"] == live_status
    assert state["is_cloud_control_auth"] is True
