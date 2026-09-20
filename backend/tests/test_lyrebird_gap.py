import asyncio
from app.vehicles.live import LyrebirdLiveBridge

class Redis:
    async def publish(self, channel, value): pass
class Collector:
    def set_publisher(self, publisher): pass
    def snapshot(self, host): return {"source":"lyrebird_mavlink2"}

class Reader:
    def __init__(self): self.once=False
    async def readline(self):
        if not self.once:
            self.once=True
            return b'{"telemetryMode":"gap","zoomRatio":2.0}\n'
        raise ConnectionError()
class Writer:
    def __init__(self): self.data=b""
    def write(self, data): self.data+=data
    async def drain(self): pass
    def close(self): pass
    async def wait_closed(self): pass

def test_live_bridge_requests_gap_mode(monkeypatch):
    from app.vehicles import live as module
    writer=Writer(); reader=Reader()
    async def open_connection(host, port): return reader, writer
    monkeypatch.setattr(module.asyncio, "open_connection", open_connection)
    bridge=LyrebirdLiveBridge(Redis(), Collector())
    async def publish(host, telemetry): raise asyncio.CancelledError()
    bridge._publish=publish
    async def run():
        try: await bridge._tcp_loop("10.0.0.2")
        except asyncio.CancelledError: pass
    asyncio.run(run())
    assert writer.data.startswith(b"MODE=GAP\n")
