from types import SimpleNamespace
from app.vehicles.lyrebird import merge_transport_telemetry
from app.vehicles.mavlink import normalize_mavlink_message

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
