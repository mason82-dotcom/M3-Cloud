import math
from types import SimpleNamespace
from app.vehicles.lyrebird import merge_dicts, merge_transport_telemetry
from app.vehicles.mavlink import normalize_mavlink_message, decode_lyrebird_frame, _mavlink2_frames

class Msg(SimpleNamespace):
    def get_type(self): return self.kind

def test_global_position_preserves_both_altitude_references():
    patch = normalize_mavlink_message(Msg(kind="GLOBAL_POSITION_INT", lat=491000000, lon=85000000, alt=143250, relative_alt=72500, vx=100, vy=200, vz=-50, hdg=12345))
    assert patch["amsl_altitude_m"] == 143.25
    assert patch["relative_altitude_m"] == 72.5
    assert patch["vertical_speed_mps"] == -0.5

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
