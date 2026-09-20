from app.flights.detector import DetectorState, FlightDecision, FlightDetector
from app.flights.service import haversine_m


def sample(*, mode: int, altitude: float = 0.0, horizontal: float = 0.0, vertical: float = 0.0):
    return {
        "mode_code": mode,
        "relative_altitude_m": altitude,
        "horizontal_speed_mps": horizontal,
        "vertical_speed_mps": vertical,
    }


def test_automatic_takeoff_starts_immediately() -> None:
    detector = FlightDetector()
    state = DetectorState()
    assert detector.evaluate(state, sample(mode=4)) is FlightDecision.START
    assert state.active is True


def test_manual_airborne_start_requires_two_confirmations() -> None:
    detector = FlightDetector()
    state = DetectorState()
    airborne = sample(mode=3, altitude=1.4, horizontal=1.0)
    assert detector.evaluate(state, airborne) is FlightDecision.NONE
    assert detector.evaluate(state, airborne) is FlightDecision.START


def test_noise_does_not_start_flight() -> None:
    detector = FlightDetector()
    state = DetectorState()
    assert detector.evaluate(state, sample(mode=0, altitude=1.2)) is FlightDecision.NONE
    assert detector.evaluate(state, sample(mode=3, altitude=0.2, horizontal=0.1)) is FlightDecision.NONE
    assert state.active is False


def test_landing_requires_three_standby_samples() -> None:
    detector = FlightDetector()
    state = DetectorState(active=True)
    landed = sample(mode=0, altitude=0.2, horizontal=0.1, vertical=0.1)
    assert detector.evaluate(state, landed) is FlightDecision.NONE
    assert detector.evaluate(state, landed) is FlightDecision.NONE
    assert detector.evaluate(state, landed) is FlightDecision.END
    assert state.active is False


def test_landing_counter_resets_when_aircraft_moves_again() -> None:
    detector = FlightDetector()
    state = DetectorState(active=True)
    landed = sample(mode=0, altitude=0.2, horizontal=0.1, vertical=0.1)
    assert detector.evaluate(state, landed) is FlightDecision.NONE
    assert detector.evaluate(state, sample(mode=3, altitude=2.0, horizontal=1.0)) is FlightDecision.NONE
    assert detector.evaluate(state, landed) is FlightDecision.NONE


def test_haversine_distance_is_metric() -> None:
    distance = haversine_m(49.0, 8.0, 49.001, 8.0)
    assert 110.0 < distance < 112.5
