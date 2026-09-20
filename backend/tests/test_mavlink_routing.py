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



class _Transport:
    def __init__(self):
        self.frames = []

    def sendto(self, frame, address):
        self.frames.append((frame, address))


def test_mission_transmit_sequence_increments_across_packets():
    collector = LyrebirdMavlinkCollector()
    assert collector._bind_system("10.0.0.1", 42)
    transport = _Transport()
    collector._transport = transport

    collector.send_mission_count("10.0.0.1", 1)
    collector.send_mission_item_int(
        "10.0.0.1",
        {
            "seq": 0,
            "frame": 6,
            "command": 16,
            "current": 0,
            "autocontinue": 1,
            "param1": 0.0,
            "param2": None,
            "param3": 0.0,
            "param4": None,
            "x": 490000000,
            "y": 80000000,
            "z": 50.0,
            "mission_type": 0,
        },
    )

    assert len(transport.frames) == 2
    assert transport.frames[0][0][4] == 0
    assert transport.frames[1][0][4] == 1
