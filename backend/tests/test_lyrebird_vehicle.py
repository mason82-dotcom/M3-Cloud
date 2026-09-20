from app.vehicles.lyrebird import normalize_config


def test_normalize_lyrebird_config_uses_documented_identity_fields():
    vehicle = normalize_config(
        "192.168.1.42",
        {
            "droneName": "M3T-01",
            "aircraftModel": "DJI Mavic 3 Thermal",
            "aircraftSerialNumber": "SN123",
        },
    )
    assert vehicle.id == "lyrebird:SN123"
    assert vehicle.sn == "SN123"
    assert vehicle.name == "M3T-01"
    assert vehicle.model == "DJI Mavic 3 Thermal"
    assert vehicle.source == "lyrebird"
    assert vehicle.online is True
    assert vehicle.telemetry is None


def test_normalize_lyrebird_config_has_safe_identity_fallbacks():
    vehicle = normalize_config("10.0.0.8", {"droneName": "field-drone"})
    assert vehicle.sn == "10.0.0.8"
    assert vehicle.name == "field-drone"
    assert vehicle.model == "LYREBIRD_AIRCRAFT"
