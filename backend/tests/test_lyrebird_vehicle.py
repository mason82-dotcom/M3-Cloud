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
