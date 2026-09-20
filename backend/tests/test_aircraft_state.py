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
    assert common["mode"] is None and common["armed"] is None and common["is_flying"] is None
    assert common["native"]=={"dji_mode_code":17,"dji_mode_code_reason":3}
    assert "mavlink_custom_mode" not in common["native"]
