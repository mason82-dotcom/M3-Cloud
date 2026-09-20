from app.vehicles.lyrebird import normalize_config, normalize_telemetry

def test_normalize_config_matches_actual_lyrebird_config_surface():
    vehicle = normalize_config("192.168.1.42", {"droneName":"field-drone","ipAddress":"192.168.1.42","httpPort":8080,"telemetryPort":8081,"videoMode":"whip","hasThermal":True})
    assert vehicle.id == "lyrebird:192.168.1.42"
    assert vehicle.sn == "lyrebird@192.168.1.42"
    assert vehicle.name == "field-drone"
    assert vehicle.model == "LYREBIRD_AIRCRAFT"

def test_tcp_telemetry_keeps_aircraft_and_controller_position_separate():
    state = normalize_telemetry({"location":{"latitude":49.1,"longitude":8.5},"altitude":42.5,"heading":123.0,"batteryLevel":81,"satelliteCount":19,"remainingFlightTime":900,"phoneLocation":{"latitude":49.2,"longitude":8.6,"heading":200.0,"battery":66,"wifiRssi":-55}}, now_ms=1000)
    assert state["latitude"] == 49.1
    assert state["longitude"] == 8.5
    assert state["relative_altitude_m"] == 42.5
    assert state["controller"]["latitude"] == 49.2
    assert state["controller"]["longitude"] == 8.6
    assert state["battery"]["capacity_percent"] == 81
    assert "ellipsoid_height_m" not in state
    assert "rtk" not in state


def test_camera_capability_probe_provides_explicit_m3m_identity():
    vehicle = normalize_config(
        "192.168.1.42",
        {"droneName": "field-drone", "hasThermal": False},
        {},
        {
            "componentIndex": "LEFT_OR_MAIN",
            "connected": True,
            "cameraType": "M3M",
            "firmwareVersion": "01.00",
            "cameraMode": "PHOTO_NORMAL",
            "cameraModeRange": ["PHOTO_NORMAL"],
            "liveViewSource": "RGB_CAMERA",
            "liveViewSourceRange": ["RGB_CAMERA"],
            "captureStoredSources": ["RGB_CAMERA", "NDVI_CAMERA", "MS_G_CAMERA", "MS_R_CAMERA", "MS_RE_CAMERA", "MS_NIR_CAMERA"],
            "captureCurrentScreen": False,
        },
    )
    assert vehicle.model == "M3M"
    assert vehicle.telemetry["payload"]["platform"] == "M3M"
    assert vehicle.telemetry["payload"]["multispectral"] is True
    assert vehicle.telemetry["payload"]["thermal"] is False
    assert "MS_NIR_CAMERA" in vehicle.telemetry["payload"]["camera"]["capture_stored_sources"]

def test_has_thermal_alone_does_not_claim_m3t():
    vehicle = normalize_config("10.0.0.8", {"droneName": "unknown", "hasThermal": True}, {})
    assert vehicle.model == "LYREBIRD_AIRCRAFT"
    assert vehicle.telemetry["payload"]["platform"] == "UNKNOWN"
