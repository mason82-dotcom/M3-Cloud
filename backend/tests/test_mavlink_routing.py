from app.vehicles.mavlink import LyrebirdMavlinkCollector, MAVLINK_ROUTE_STALE_TIMEOUT_S
import time

def test_duplicate_system_id_is_rejected_until_existing_route_stale():
    c=LyrebirdMavlinkCollector(); assert c._bind_system("10.0.0.1",42)
    c._seen["10.0.0.1"]=time.monotonic(); assert not c._bind_system("10.0.0.2",42)
    assert c.route_status("10.0.0.2")["duplicate_system_id"]==42
    c._seen["10.0.0.1"]=time.monotonic()-MAVLINK_ROUTE_STALE_TIMEOUT_S-0.1
    assert c._bind_system("10.0.0.2",42)
    assert c.route_status("10.0.0.2")=={"system_id":42,"duplicate_system_id":None}

def test_rebinding_host_releases_previous_system_id():
    c=LyrebirdMavlinkCollector(); assert c._bind_system("10.0.0.1",41); assert c._bind_system("10.0.0.1",42)
    assert 41 not in c._host_by_system and c._host_by_system[42]=="10.0.0.1"
