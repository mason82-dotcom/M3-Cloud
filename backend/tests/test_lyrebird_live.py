import asyncio
from app.vehicles.live import LyrebirdLiveBridge

class Redis:
    def __init__(self): self.messages=[]
    async def publish(self, channel, value): self.messages.append((channel,value))

class Collector:
    def set_publisher(self, publisher): self.publisher=publisher
    def snapshot(self, host): return None

def test_live_bridge_publishes_normalized_vehicle(monkeypatch):
    redis=Redis(); bridge=LyrebirdLiveBridge(redis, Collector())
    async def identity(host):
        return {"droneName":"M3M field"}, {"cameraType":"M3M","captureStoredSources":["RGB_CAMERA","MS_NIR_CAMERA"]}
    bridge._identity=identity
    asyncio.run(bridge._publish("10.0.0.2", {"latitude":49.0}))
    assert len(redis.messages)==1
    import json
    event=json.loads(redis.messages[0][1])
    assert event["type"]=="vehicle_telemetry"
    assert event["vehicle"]["model"]=="M3M"
    assert event["vehicle"]["telemetry"]["payload"]["multispectral"] is True
