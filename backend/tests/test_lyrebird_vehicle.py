from app.vehicles.lyrebird import normalize_config, normalize_telemetry

def test_normalize_config_uses_real_aircraft_serial_as_canonical_identity():
    vehicle = normalize_config(
        "192.168.1.42",
        {
            "droneName":"field-drone",
            "aircraftSerialNumber":"1581F-TEST",
            "ipAddress":"192.168.1.42",
            "httpPort":8080,
            "telemetryPort":8081,
            "videoMode":"whip",
            "hasThermal":True,
        },
    )
    assert vehicle.id == "vehicle:1581F-TEST"
    assert vehicle.sn == "1581F-TEST"
    assert vehicle.sources == ("lyrebird",)
    assert vehicle.name == "field-drone"
    assert vehicle.model == "LYREBIRD_AIRCRAFT"


def test_normalize_config_falls_back_to_host_when_serial_is_unknown():
    vehicle = normalize_config(
        "192.168.1.42",
        {"droneName":"field-drone","aircraftSerialNumber":"UNKNOWN"},
    )
    assert vehicle.id == "lyrebird:192.168.1.42"
    assert vehicle.sn == "lyrebird@192.168.1.42"

def test_tcp_telemetry_keeps_aircraft_and_controller_position_separate():
    state = normalize_telemetry({"location":{"latitude":49.1,"longitude":8.5},"altitude":42.5,"heading":123.0,"batteryLevel":81,"satelliteCount":19,"remainingFlightTime":900,"phoneLocation":{"latitude":49.2,"longitude":8.6,"heading":200.0,"battery":66,"wifiRssi":-55}}, now_ms=1000)
    assert state["latitude"] == 49.1
    assert state["longitude"] == 8.5
    assert state["relative_altitude_m"] == 42.5
    assert state["controller"]["latitude"] == 49.2
    assert state["controller"]["longitude"] == 8.6
    assert state["battery"]["capacity_percent"] == 81
    assert "ellipsoid_height_m" not in state
    assert "rtk" not in state


def test_camera_capability_probe_provides_explicit_m3m_identity():
    vehicle = normalize_config(
        "192.168.1.42",
        {"droneName": "field-drone", "hasThermal": False},
        {},
        {
            "componentIndex": "LEFT_OR_MAIN",
            "connected": True,
            "cameraType": "M3M",
            "firmwareVersion": "01.00",
            "cameraMode": "PHOTO_NORMAL",
            "cameraModeRange": ["PHOTO_NORMAL"],
            "liveViewSource": "RGB_CAMERA",
            "liveViewSourceRange": ["RGB_CAMERA"],
            "captureStoredSources": ["RGB_CAMERA", "NDVI_CAMERA", "MS_G_CAMERA", "MS_R_CAMERA", "MS_RE_CAMERA", "MS_NIR_CAMERA"],
            "recordStoredSources": ["RGB_CAMERA", "NDVI_CAMERA"],
            "captureStorageReadStatus": "OK",
            "recordStorageReadStatus": "NOT_APPLICABLE",
            "captureCurrentScreen": False,
            "visionAssist": {
                "componentIndex": "VISION_ASSIST",
                "available": True,
                "streamAvailable": True,
                "motorsOn": True,
                "availableCameraIndices": ["LEFT_OR_MAIN", "VISION_ASSIST"],
                "streamEnabled": True,
                "enabled": True,
                "direction": "FRONT",
                "directionRange": ["FRONT", "LEFT", "RIGHT", "UP", "DOWN", "AUTO"],
                "availabilityReadStatus": "OK",
                "statusReadStatus": "OK",
            },
        },
    )
    assert vehicle.model == "M3M"
    assert vehicle.telemetry["payload"]["platform"] == "M3M"
    assert vehicle.telemetry["payload"]["multispectral"] is True
    assert vehicle.telemetry["payload"]["thermal"] is False
    assert vehicle.telemetry["payload"]["camera"]["record_stored_sources"] == ["RGB_CAMERA", "NDVI_CAMERA"]
    assert vehicle.telemetry["payload"]["camera"]["capture_storage_read_status"] == "OK"
    assert vehicle.telemetry["payload"]["camera"]["record_storage_read_status"] == "NOT_APPLICABLE"
    assert "MS_NIR_CAMERA" in vehicle.telemetry["payload"]["camera"]["capture_stored_sources"]
    assert vehicle.telemetry["payload"]["vision_assist"]["component_index"] == "VISION_ASSIST"
    assert vehicle.telemetry["payload"]["vision_assist"]["available"] is True
    assert vehicle.telemetry["payload"]["vision_assist"]["stream_available"] is True
    assert vehicle.telemetry["payload"]["vision_assist"]["motors_on"] is True
    assert vehicle.telemetry["payload"]["vision_assist"]["direction"] == "FRONT"
    assert "AUTO" in vehicle.telemetry["payload"]["vision_assist"]["direction_range"]

def test_has_thermal_alone_does_not_claim_m3t():
    vehicle = normalize_config("10.0.0.8", {"droneName": "unknown", "hasThermal": True}, {})
    assert vehicle.model == "LYREBIRD_AIRCRAFT"
    assert vehicle.telemetry["payload"]["platform"] == "UNKNOWN"


def test_camera_capability_probe_accepts_explicit_platform_fallback():
    vehicle = normalize_config(
        "192.168.1.42",
        {"droneName": "field-drone", "hasThermal": False},
        {},
        {"cameraType": "NOT_SUPPORTED", "platform": "M3M", "connected": True},
    )
    assert vehicle.model == "M3M"
    assert vehicle.telemetry["payload"]["platform"] == "M3M"
    assert vehicle.telemetry["payload"]["multispectral"] is True
    assert vehicle.telemetry["payload"]["thermal"] is False


def test_provider_serializes_rc_http_identity_reads(monkeypatch):
    import asyncio
    import httpx
    from app.vehicles.lyrebird import LyrebirdVehicleProvider

    class Response:
        def __init__(self, payload):
            self._payload = payload
        def raise_for_status(self):
            return None
        def json(self):
            return self._payload

    class SingleFlightClient:
        def __init__(self):
            self.active = 0
        async def get(self, url, timeout, **kwargs):
            self.active += 1
            try:
                if self.active > 1:
                    raise httpx.ReadTimeout("concurrent RC HTTP request")
                await asyncio.sleep(0)
                if url.endswith("/config"):
                    return Response({"droneName": "field", "aircraftSerialNumber": "1581F-M3M"})
                if url.endswith("/get/camera/capabilities"):
                    return Response({"cameraType": "M3M", "platform": "M3M", "connected": True})
                if url.endswith("/config/settings"):
                    return Response({"aircraftSerialNumber": "1581F-M3M"})
                raise AssertionError(url)
            finally:
                self.active -= 1

    async def run():
        provider = LyrebirdVehicleProvider(client=SingleFlightClient())
        async def no_tcp(host):
            return None
        provider._read_telemetry = no_tcp
        vehicles = await provider.list_vehicles()
        assert len(vehicles) == 1
        assert vehicles[0].model == "M3M"
        assert vehicles[0].telemetry["payload"]["platform"] == "M3M"

    monkeypatch.setattr("app.vehicles.lyrebird.settings.lyrebird_enabled", True)
    monkeypatch.setattr("app.vehicles.lyrebird.settings.lyrebird_hosts", "192.168.178.45")
    asyncio.run(run())


def test_provider_reads_identity_before_tcp(monkeypatch):
    import asyncio
    from app.vehicles.lyrebird import LyrebirdVehicleProvider

    events = []

    class Response:
        def __init__(self, payload):
            self._payload = payload
        def raise_for_status(self):
            return None
        def json(self):
            return self._payload

    class OrderedClient:
        async def get(self, url, timeout, **kwargs):
            if url.endswith("/config"):
                events.append("config")
                return Response({"droneName": "field", "aircraftSerialNumber": "1581F-M3M"})
            if url.endswith("/get/camera/capabilities"):
                events.append("camera")
                return Response({"cameraType": "M3M", "platform": "M3M", "connected": True})
            if url.endswith("/config/settings"):
                events.append("settings")
                return Response({"aircraftSerialNumber": "1581F-M3M"})
            raise AssertionError(url)

    async def run():
        provider = LyrebirdVehicleProvider(client=OrderedClient())
        async def tcp(host):
            events.append("tcp")
            return None
        provider._read_telemetry = tcp
        vehicles = await provider.list_vehicles()
        assert len(vehicles) == 1
        assert vehicles[0].model == "M3M"

    monkeypatch.setattr("app.vehicles.lyrebird.settings.lyrebird_enabled", True)
    monkeypatch.setattr("app.vehicles.lyrebird.settings.lyrebird_hosts", "192.168.178.45")
    asyncio.run(run())
    assert events == ["config", "camera", "settings", "tcp"]
