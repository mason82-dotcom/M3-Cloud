from types import SimpleNamespace

import pytest

from app.config import Settings
from app.dji.cloud_control import (
    DJICloudControl,
    DJICloudControlConfigError,
    DJICloudControlNotAuthorized,
    drc_broker_for,
)


class FakeServices:
    def __init__(self):
        self.calls = []

    async def call(self, gateway_sn, method, data):
        self.calls.append((gateway_sn, method, data))
        return SimpleNamespace(
            gateway_sn=gateway_sn,
            method=method,
            tid="tid",
            bid="bid",
            result=0,
            output=None,
        )


class FakeGateways:
    def __init__(self, *, authorized=False, online=True):
        self.authorized = authorized
        self.online = online

    async def get(self, gateway_sn):
        return SimpleNamespace(
            identity={
                "sn": gateway_sn,
                "online": self.online,
            },
            thing_state={
                "is_cloud_control_auth": self.authorized,
            },
            aircraft=(),
        )


def drc_settings(**updates):
    return Settings(_env_file=None).model_copy(
        update={
            "dji_drc_broker_address": "192.168.178.45:1883",
            "dji_drc_client_id_prefix": "m3cloud-drc-",
            "dji_drc_username": "drc",
            "dji_drc_password": "secret",
            "dji_drc_enable_tls": False,
            "dji_drc_credential_ttl_seconds": 3600,
            "dji_drc_osd_frequency_hz": 10,
            "dji_drc_hsi_frequency_hz": 1,
            **updates,
        }
    )


def test_drc_broker_payload_uses_absolute_expiry_and_gateway_client_id():
    broker = drc_broker_for(
        drc_settings(),
        gateway_sn="RC123",
        now_s=1_700_000_000,
    )

    assert broker.as_dict() == {
        "address": "192.168.178.45:1883",
        "client_id": "m3cloud-drc-RC123",
        "username": "drc",
        "password": "secret",
        "expire_time": 1_700_003_600,
        "enable_tls": False,
    }


@pytest.mark.parametrize(
    "address",
    ["", "tcp://broker:1883", "broker", "broker:not-a-port"],
)
def test_drc_broker_configuration_fails_closed(address):
    with pytest.raises(DJICloudControlConfigError):
        drc_broker_for(
            drc_settings(dji_drc_broker_address=address),
            gateway_sn="RC123",
        )


@pytest.mark.asyncio
async def test_cloud_control_authorization_uses_documented_service_payload():
    services = FakeServices()
    control = DJICloudControl(
        services,
        FakeGateways(),
        drc_settings(),
    )

    result = await control.request_authorization(
        "RC123",
        user_id="roman",
        user_callsign="M3-Cloud",
    )

    assert result["method"] == "cloud_control_auth_request"
    assert services.calls == [
        (
            "RC123",
            "cloud_control_auth_request",
            {
                "user_id": "roman",
                "user_callsign": "M3-Cloud",
                "control_keys": ["flight"],
            },
        )
    ]


@pytest.mark.asyncio
async def test_drc_enter_requires_reported_cloud_control_authority():
    services = FakeServices()
    control = DJICloudControl(
        services,
        FakeGateways(authorized=False),
        drc_settings(),
    )

    with pytest.raises(DJICloudControlNotAuthorized):
        await control.enter_drc("RC123")

    assert services.calls == []


@pytest.mark.asyncio
async def test_drc_enter_uses_dedicated_broker_and_documented_frequencies(monkeypatch):
    services = FakeServices()
    control = DJICloudControl(
        services,
        FakeGateways(authorized=True),
        drc_settings(),
    )
    monkeypatch.setattr("app.dji.cloud_control.time.time", lambda: 1_700_000_000)

    result = await control.enter_drc("RC123")

    assert result["method"] == "drc_mode_enter"
    gateway_sn, method, data = services.calls[0]
    assert gateway_sn == "RC123"
    assert method == "drc_mode_enter"
    assert data["mqtt_broker"]["address"] == "192.168.178.45:1883"
    assert data["mqtt_broker"]["client_id"] == "m3cloud-drc-RC123"
    assert data["mqtt_broker"]["expire_time"] == 1_700_003_600
    assert data["osd_frequency"] == 10
    assert data["hsi_frequency"] == 1


@pytest.mark.asyncio
async def test_release_cloud_control_releases_only_flight_authority():
    services = FakeServices()
    control = DJICloudControl(
        services,
        FakeGateways(authorized=True),
        drc_settings(),
    )

    await control.release("RC123")

    assert services.calls == [
        (
            "RC123",
            "cloud_control_release",
            {"control_keys": ["flight"]},
        )
    ]
