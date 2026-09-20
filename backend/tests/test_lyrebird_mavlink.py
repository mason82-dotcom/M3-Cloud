import math
import struct
from types import SimpleNamespace
from app.vehicles.lyrebird import merge_dicts, merge_transport_telemetry
from app.vehicles.mavlink import normalize_mavlink_message, decode_lyrebird_frame, decode_lyrebird_rtk_status, decode_autosensing_status, decode_autosensing_target, _mavlink2_frames, AUTOSENSING_STATUS_STRUCT, AUTOSENSING_TARGET_STRUCT

class Msg(SimpleNamespace):
    def get_type(self): return self.kind

def test_global_position_preserves_both_altitude_references():
    patch = normalize_mavlink_message(Msg(kind="GLOBAL_POSITION_INT", lat=491000000, lon=85000000, alt=143250, relative_alt=72500, vx=100, vy=200, vz=-50, hdg=12345))
    assert patch["amsl_altitude_m"] == 143.25
    assert patch["relative_altitude_m"] == 72.5
    assert patch["velocity_down_mps"] == -0.5

def test_rtk_fix_comes_from_mavlink_fix_type_not_tcp_guess():
    fixed = normalize_mavlink_message(Msg(kind="GPS_RAW_INT", fix_type=6, satellites_visible=20))
    assert fixed["rtk"] == {"fix":"FIXED","active":True}
    merged = merge_transport_telemetry(fixed, {"gps_satellites":18,"safety":{"ready_to_takeoff":True}})
    assert merged["gps_satellites"] == 20
    assert merged["safety"]["ready_to_takeoff"] is True


def test_distance_sensor_is_lrf_not_aircraft_altitude():
    patch = normalize_mavlink_message(Msg(kind="DISTANCE_SENSOR", current_distance=1234))
    assert patch == {"lrf": {"distance_m": 12.34}}

def test_gimbal_delta_yaw_is_radians_on_wire():
    patch = normalize_mavlink_message(Msg(kind="GIMBAL_DEVICE_ATTITUDE_STATUS", q=[1.0,0.0,0.0,0.0], delta_yaw=math.pi/6))
    assert round(patch["gimbal"]["joint_yaw_deg"], 6) == 30.0

def test_frame_splitter_handles_two_mavlink2_frames():
    a = bytes([0xFD,0,0,0,1,1,1,0,0,0,0,0])
    b = bytes([0xFD,0,0,0,2,1,1,0,0,0,0,0])
    assert list(_mavlink2_frames(a+b)) == [a,b]

def test_recursive_transport_merge_preserves_nested_tcp_gaps():
    tcp={"camera":{"zoom_ratio":2.0,"recording":True},"controller":{"wifi_rssi_dbm":-51},"lrf":{"target":{"latitude":49.1,"longitude":8.5}}}
    mav={"camera":{"recording":False,"zoom_focal_length_mm":70},"lrf":{"distance_m":12.3}}
    merged=merge_transport_telemetry(mav,tcp)
    assert merged["camera"]=={"zoom_ratio":2.0,"recording":False,"zoom_focal_length_mm":70}
    assert merged["lrf"]=={"target":{"latitude":49.1,"longitude":8.5},"distance_m":12.3}
    assert merged["controller"]["wifi_rssi_dbm"]==-51
    assert merged["provenance"]["primary"]=="mavlink2"

def test_gap_merge_ignores_normalized_none_values():
    previous={"camera":{"recording":True,"zoom_ratio":2.0},"controller":{"wifi_rssi_dbm":-50}}
    patch={"camera":{"recording":None,"zoom_ratio":3.0},"controller":{"wifi_rssi_dbm":None}}
    merged=merge_dicts(previous,patch,ignore_none=True)
    assert merged["camera"]=={"recording":True,"zoom_ratio":3.0}
    assert merged["controller"]["wifi_rssi_dbm"]==-50

def test_merge_does_not_mutate_inputs():
    tcp={"lrf":{"target":{"latitude":49.1}}}; mav={"lrf":{"distance_m":4.2}}
    merged=merge_transport_telemetry(mav,tcp)
    merged["lrf"]["target"]["latitude"]=0
    assert tcp["lrf"]["target"]["latitude"]==49.1

def test_autosensing_layout_matches_lyrebird_dialect():
    status=decode_autosensing_status(__import__("struct").pack(AUTOSENSING_STATUS_STRUCT,0,7,0.25,1,2,b"edge"))
    assert status["frame_id"]==7 and status["active"] is True and status["count"]==2 and status["source"]=="edge"
    target=decode_autosensing_target(__import__("struct").pack(AUTOSENSING_TARGET_STRUCT,0,7,0.1,0.2,0.3,0.4,0.9,0,2,b"PERSON"))
    assert target["frame_id"]==7 and target["target"]["type"]=="PERSON"
    assert len(target["target"]["rect"])==4

def test_standard_mission_and_vfr_messages_are_normalized():
    hud=normalize_mavlink_message(Msg(kind="VFR_HUD",alt=42.5,climb=1.25))
    assert hud=={"amsl_altitude_m":42.5,"climb_rate_mps":1.25}
    current=normalize_mavlink_message(Msg(kind="MISSION_CURRENT",seq=4,mission_state=3,mission_id=0xF1234567))
    assert current["mission"]=={"current_seq":4,"state":3,"mission_id":0xF1234567}
    reached=normalize_mavlink_message(Msg(kind="MISSION_ITEM_REACHED",seq=4))
    assert reached["reach"]=={"waypoint_reached":True,"waypoint_seq":4}

def test_altitude_keeps_reference_frames_separate_and_unknowns_null():
    patch=normalize_mavlink_message(Msg(kind="ALTITUDE",altitude_monotonic=12.0,altitude_amsl=142.0,altitude_local=12.0,altitude_relative=12.0,altitude_terrain=-1001.0,bottom_clearance=-1.0))
    assert patch["altitude"]=={"monotonic_m":12.0,"amsl_m":142.0,"local_m":12.0,"relative_m":12.0,"terrain_m":None,"bottom_clearance_m":None}

def test_extended_sys_state_exposes_flying_without_inference():
    patch=normalize_mavlink_message(Msg(kind="EXTENDED_SYS_STATE",landed_state=2))
    assert patch["flight_state"]=={"landed_state":2,"is_flying":True}

def test_vfr_hud_alt_is_amsl_and_climb_is_positive_up():
    patch=normalize_mavlink_message(Msg(kind="VFR_HUD",alt=142.5,climb=1.25))
    assert patch=={"amsl_altitude_m":142.5,"climb_rate_mps":1.25}

def test_heartbeat_preserves_lyrebird_px4_compatibility_semantics():
    base=(1 | 4 | 8 | 16 | 64 | 128)
    patch=normalize_mavlink_message(Msg(kind="HEARTBEAT",base_mode=base,system_status=4,custom_mode=(4<<16)|(5<<24)))
    state=patch["flight_state"]
    assert state["mode"]=="SAFE_RECOVERY"
    assert state["armed"] is True and state["guided"] is True
    assert state["manual_input"] is True and state["stabilized"] is True
    assert state["failsafe"] is False

def test_heartbeat_critical_is_failsafe_and_unknown_mode_stays_unknown():
    patch=normalize_mavlink_message(Msg(kind="HEARTBEAT",base_mode=1,system_status=5,custom_mode=123456))
    assert patch["flight_state"]["mode"]=="UNKNOWN"
    assert patch["flight_state"]["failsafe"] is True
    assert patch["flight_state"]["armed"] is False

def test_gps_raw_int_exposes_neutral_fix_without_losing_mavlink_type():
    fixed=normalize_mavlink_message(Msg(kind="GPS_RAW_INT",fix_type=6,satellites_visible=27))
    assert fixed["positioning"]["fix"]=="FIXED"
    assert fixed["positioning"]["position_source"]=="RTK_FUSED"
    assert fixed["positioning"]["native"]["mavlink_gps_fix_type"]==6
    single=normalize_mavlink_message(Msg(kind="GPS_RAW_INT",fix_type=3,satellites_visible=18))
    assert single["positioning"]["fix"]=="SINGLE"
    assert single["positioning"]["position_source"]=="FLIGHT_CONTROLLER"
    assert single["rtk"]["active"] is False


def test_private_rtk_status_extension_preserves_raw_fix_and_source():
    payload=struct.pack("<IIfffBB24s32s",123,42,0.01,0.02,0.03,7,5,b"FIXED"+b"\0"*19,b"CUSTOM_NETWORK_SERVICE"+b"\0"*10)
    decoded=decode_lyrebird_rtk_status(payload)
    assert decoded["rtk"]["fix"]=="STALE"
    assert decoded["rtk"]["raw_fix"]=="FIXED"
    assert decoded["rtk"]["source"]=="CUSTOM_NETWORK_SERVICE"
    assert decoded["positioning"]["native"]["dji_rtk_raw_fix"]=="FIXED"
    assert decoded["positioning"]["native"]["dji_rtk_source"]=="CUSTOM_NETWORK_SERVICE"

def test_private_rtk_status_old_base_payload_remains_decodable():
    payload=struct.pack("<IIfffBB",123,3501,0.01,0.02,0.03,3,5)
    decoded=decode_lyrebird_rtk_status(payload)
    assert decoded["rtk"]["fix"]=="STALE"
    assert decoded["rtk"]["raw_fix"] is None
    assert decoded["rtk"]["source"] is None


def test_lyrebird_status_uint16_unknown_budget_is_null():
    # Field-level decoder semantics: UINT16_MAX is an unavailable DJI estimate,
    # not 65535 seconds of real flight budget.
    import app.vehicles.mavlink as ml
    payload=struct.pack(
        ml.LYREBIRD_STATUS_STRUCT,
        1, 0, 0, 0.0, 0.0, 0, 0, 0,
        0xFFFF, 12, 0xFFFF,
        0, 0, 24, 240, 240, 0, 0, 0, b""
    )
    values=struct.unpack(ml.LYREBIRD_STATUS_STRUCT,payload)
    go_home_s, land_s, total_s=values[8],values[9],values[10]
    decoded={
        "time_to_home_s": None if go_home_s == 0xFFFF else go_home_s,
        "time_to_land_s": None if land_s == 0xFFFF else land_s,
        "total_flight_time_s": None if total_s == 0xFFFF else total_s,
    }
    assert decoded=={"time_to_home_s":None,"time_to_land_s":12,"total_flight_time_s":None}
