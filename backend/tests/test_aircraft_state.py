from app.vehicles.state import normalize_aircraft_state

def test_lyrebird_common_state_preserves_native_mavlink_and_dji_mode():
    telemetry={"flight_mode":"GPS_NORMAL","flight_state":{"mode":"POSITION_HOLD","custom_mode":196608,"system_status":4,"armed":True,"is_flying":True,"failsafe":False,"landed_state":2}}
    state=normalize_aircraft_state(telemetry,source="lyrebird")
    common=state["aircraft_state"]
    assert common["mode"]=="POSITION_HOLD" and common["armed"] is True and common["is_flying"] is True
    assert common["native"]["mavlink_custom_mode"]==196608
    assert common["native"]["dji_flight_mode"]=="GPS_NORMAL"

def test_dji_cloud_mode_code_is_not_reinterpreted_as_mavlink_mode():
    state=normalize_aircraft_state({"mode_code":17,"mode_code_reason":3},source="dji_cloud")
    common=state["aircraft_state"]
    assert common["mode"]=="LIVE_FLIGHT_CONTROLS" and common["armed"] is None and common["is_flying"] is None
    assert common["native"]=={"dji_mode_code":17,"dji_mode_code_reason":3}
    assert "mavlink_custom_mode" not in common["native"]

def test_dji_cloud_documented_home_and_rtk_are_exposed_without_flight_inference():
    telemetry={"mode_code":9,"home_latitude":49.1,"home_longitude":8.5,"home_distance_m":42.0,
               "position_state":{"convergence":"CONVERGED","quality":10,"gps_satellites":18,"rtk_satellites":27}}
    common=normalize_aircraft_state(telemetry,source="dji_cloud")["aircraft_state"]
    assert common["mode"]=="AUTO_RETURN_TO_HOME"
    assert common["home"]=={"latitude":49.1,"longitude":8.5,"distance_m":42.0}
    assert common["positioning"]["rtk_fixed"] is True
    assert common["positioning"]["rtk_satellites"]==27
    assert common["armed"] is None and common["is_flying"] is None and common["failsafe"] is None

def test_unknown_dji_cloud_mode_code_remains_unmapped():
    common=normalize_aircraft_state({"mode_code":999},source="dji_cloud")["aircraft_state"]
    assert common["mode"] is None and common["native"]["dji_mode_code"]==999

def test_dji_positioning_does_not_translate_quality_into_mavlink_fix_type():
    common=normalize_aircraft_state({"position_state":{"convergence":"CONVERGING","quality":10,"gps_satellites":18,"rtk_satellites":20}},source="dji_cloud")["aircraft_state"]
    assert common["positioning"]["rtk_fixed"] is False
    assert common["positioning"]["fix"]=="UNKNOWN"
    assert common["positioning"]["native"]=={"dji_quality":10,"dji_convergence":"CONVERGING"}
