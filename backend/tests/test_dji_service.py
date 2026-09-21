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
