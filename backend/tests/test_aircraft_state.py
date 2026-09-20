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

def test_dji_cloud_documented_home_and_positioning_are_exposed_without_fix_inference():
    telemetry={"mode_code":9,"home_latitude":49.1,"home_longitude":8.5,"home_distance_m":42.0,
               "position_state":{"convergence":"CONVERGED","quality":5,"gps_satellites":18,"rtk_satellites":27}}
    common=normalize_aircraft_state(telemetry,source="dji_cloud")["aircraft_state"]
    assert common["mode"]=="AUTO_RETURN_TO_HOME"
    assert common["home"]=={"latitude":49.1,"longitude":8.5,"distance_m":42.0}
    assert common["positioning"]["rtk_fixed"] is None
    assert common["positioning"]["fix"]=="UNKNOWN"
    assert common["positioning"]["rtk_satellites"]==27
    assert common["positioning"]["rtk"]["fix"]=="UNKNOWN"
    assert common["positioning"]["rtk"]["satellites"]==27
    assert common["positioning"]["rtk"]["convergence"]=="CONVERGED"
    assert common["positioning"]["rtk"]["quality"]==5
    assert common["positioning"]["rtk"]["enabled"] is None
    assert common["armed"] is None and common["is_flying"] is None and common["failsafe"] is None

def test_unknown_dji_cloud_mode_code_remains_unmapped():
    common=normalize_aircraft_state({"mode_code":999},source="dji_cloud")["aircraft_state"]
    assert common["mode"] is None and common["native"]["dji_mode_code"]==999

def test_dji_positioning_does_not_translate_quality_into_mavlink_fix_type():
    common=normalize_aircraft_state({"position_state":{"convergence":"CONVERGED","quality":10,"gps_satellites":18,"rtk_satellites":20}},source="dji_cloud")["aircraft_state"]
    assert common["positioning"]["rtk_fixed"] is None
    assert common["positioning"]["fix"]=="UNKNOWN"
    assert common["positioning"]["rtk"]["fix"]=="UNKNOWN"
    assert common["positioning"]["rtk"]["convergence"]=="CONVERGED"
    assert common["positioning"]["rtk"]["quality"]==10
    assert common["positioning"]["rtk"]["raw_fix"] is None
    assert common["positioning"]["native"]=={"dji_quality":10,"dji_convergence":"CONVERGING","dji_is_fixed_code":None}

def test_lyrebird_stale_rtk_overrides_retained_fixed_gps_state():
    telemetry={
        "positioning":{"fix":"FIXED","position_source":"RTK_FUSED","gps_satellites":24},
        "rtk":{"fix":"STALE","enabled":True,"connected":True,"healthy":False,"age_ms":3501},
    }
    common=normalize_aircraft_state(telemetry,source="lyrebird")["aircraft_state"]
    assert common["positioning"]["fix"]=="STALE"
    assert common["positioning"]["rtk_stale"] is True
    assert common["positioning"]["position_source"]=="FLIGHT_CONTROLLER"
    assert common["positioning"]["gps_satellites"]==24

def test_lyrebird_fresh_rtk_restores_fused_position_source():
    telemetry={"positioning":{"fix":"SINGLE","position_source":"FLIGHT_CONTROLLER"},
               "rtk":{"fix":"FIXED","enabled":True,"connected":True,"healthy":True,"age_ms":50}}
    positioning=normalize_aircraft_state(telemetry,source="lyrebird")["aircraft_state"]["positioning"]
    assert positioning["fix"]=="FIXED"
    assert positioning["rtk_stale"] is False
    assert positioning["position_source"]=="RTK_FUSED"


def test_lyrebird_positioning_contains_canonical_rtk_diagnostics():
    telemetry={
        "positioning":{"fix":"SINGLE","position_source":"FLIGHT_CONTROLLER","gps_satellites":19,
                       "native":{"mavlink_gps_fix_type":3}},
        "rtk":{"fix":"STALE","raw_fix":"FIXED","enabled":True,"connected":True,"healthy":False,
               "age_ms":4123,"source":"CUSTOM_NETWORK_SERVICE",
               "std_latitude_m":0.012,"std_longitude_m":0.013,"std_altitude_m":0.021},
    }
    positioning=normalize_aircraft_state(telemetry,source="lyrebird")["aircraft_state"]["positioning"]
    assert positioning["rtk"]=={
        "enabled":True,"connected":True,"healthy":False,"fix":"STALE","raw_fix":"FIXED",
        "age_ms":4123,"source":"CUSTOM_NETWORK_SERVICE",
        "std_latitude_m":0.012,"std_longitude_m":0.013,"std_altitude_m":0.021,
    }
    assert positioning["native"]["mavlink_gps_fix_type"]==3
    assert positioning["native"]["dji_rtk_raw_fix"]=="FIXED"
    assert positioning["native"]["dji_rtk_source"]=="CUSTOM_NETWORK_SERVICE"

def test_lyrebird_positioning_does_not_invent_rtk_diagnostics_without_private_status():
    telemetry={"positioning":{"fix":"SINGLE","position_source":"FLIGHT_CONTROLLER","gps_satellites":12}}
    positioning=normalize_aircraft_state(telemetry,source="lyrebird")["aircraft_state"]["positioning"]
    assert "rtk" not in positioning
    assert "native" not in positioning


def test_dji_cloud_positioning_preserves_is_fixed_code_without_inventing_mavlink_fix():
    telemetry={"position_state":{"code":1,"convergence":"CONVERGING","quality":5,
                                "gps_satellites":15,"rtk_satellites":18}}
    positioning=normalize_aircraft_state(telemetry,source="dji_cloud")["aircraft_state"]["positioning"]
    assert positioning["fix"]=="UNKNOWN"
    assert positioning["rtk"]["fix"]=="UNKNOWN"
    assert positioning["rtk"]["satellites"]==18
    assert positioning["rtk"]["enabled"] is None
    assert positioning["rtk"]["connected"] is None
    assert positioning["rtk"]["healthy"] is None
    assert positioning["native"]["dji_is_fixed_code"]==1
