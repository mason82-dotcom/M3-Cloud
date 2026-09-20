import asyncio
import time
from app.vehicles.live import LyrebirdLiveBridge

class Redis:
    async def publish(self, channel, value): pass
class Collector:
    def __init__(self): self.value=None
    def set_publisher(self, publisher): pass
    def snapshot(self, host): return self.value

def test_health_distinguishes_online_degraded_stale_offline(monkeypatch):
    from app.vehicles import live as module
    monkeypatch.setattr(module.settings, "lyrebird_hosts", "10.0.0.2")
    collector=Collector(); bridge=LyrebirdLiveBridge(Redis(), collector)
    assert bridge.health()["status"]=="OFFLINE"
    bridge._http_seen["10.0.0.2"]=time.monotonic()
    assert bridge.health()["status"]=="STALE"
    collector.value={"source":"lyrebird_mavlink2"}
    assert bridge.health()["status"]=="DEGRADED"
    bridge._tcp_seen["10.0.0.2"]=time.monotonic()
    assert bridge.health()["status"]=="ONLINE"
