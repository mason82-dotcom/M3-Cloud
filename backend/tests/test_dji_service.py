from app.dji.service import DJIService


def test_dji_service_create_wires_primary_domains() -> None:
    redis = object()

    service = DJIService.create(redis)  # type: ignore[arg-type]

    assert service.router.registry is service.registry
    assert service.router.publisher is service.transport
    assert service.router.telemetry is service.telemetry
    assert service.router.transactions is service.transactions
    assert service.router.events is service.events
    assert service.router.requests is service.requests
    assert service.router.drc_state is service.drc_state

    assert service.devices.registry is service.registry
    assert service.devices.telemetry is service.telemetry
    assert service.devices.properties is service.properties
    assert service.gateways.registry is service.registry
    assert service.gateways.telemetry is service.telemetry
    assert service.payloads.services is service.services
    assert service.cloud_control.services is service.services
    assert service.cloud_control.gateways is service.gateways
    assert service.cloud_control.drc_sessions is service.drc_sessions
    assert service.drc_sessions.channel is service.drc_channel


def test_dji_service_cloud_control_is_wired_without_polluting_router() -> None:
    redis = object()

    service = DJIService.create(redis)  # type: ignore[arg-type]

    assert service.cloud_control.services is service.services
    assert service.cloud_control.gateways is service.gateways
    assert service.cloud_control.settings is not None
    assert not hasattr(service.router, "cloud_control")
