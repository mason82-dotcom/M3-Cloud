from app.vehicles.payloads import AircraftPlatform, capabilities_for, platform_from_camera_type, platform_from_explicit_model

def test_m3_family_capabilities_stay_separate():
    m3e = capabilities_for(AircraftPlatform.M3E)
    m3t = capabilities_for(AircraftPlatform.M3T)
    m3m = capabilities_for(AircraftPlatform.M3M)
    assert m3e.thermal is False and m3e.multispectral is False
    assert m3t.thermal is True and m3t.multispectral is False and m3t.lrf is True
    assert m3m.thermal is False and m3m.multispectral is True
    assert "M3M_RGB_MULTISPECTRAL" in m3m.capture_profiles

def test_camera_type_policy_matches_lyrebird_and_fails_closed():
    assert platform_from_camera_type("M3E") == AircraftPlatform.M3E
    assert platform_from_camera_type("M3TA") == AircraftPlatform.M3T
    assert platform_from_camera_type("M3M") == AircraftPlatform.M3M
    assert platform_from_camera_type("future_camera") == AircraftPlatform.UNKNOWN

def test_thermal_flag_is_not_model_identity():
    # LYREBIRD_CONFIG.hasThermal is a capability only; this resolver requires explicit model identity.
    assert platform_from_explicit_model(None) == AircraftPlatform.UNKNOWN
    assert platform_from_explicit_model("Mavic 3 Thermal") == AircraftPlatform.M3T
