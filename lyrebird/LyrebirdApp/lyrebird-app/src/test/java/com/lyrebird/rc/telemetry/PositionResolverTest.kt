package com.lyrebird.rc.telemetry

import org.junit.Assert.assertEquals
import org.junit.Test

class PositionResolverTest {

    @Test
    fun fixedHealthyRtkUsesFusedHorizontalPosition() {
        val result = PositionResolver.resolve(
            flightControllerLatitudeDeg = 49.0,
            flightControllerLongitudeDeg = 8.0,
            flightControllerAltitudeM = 120.0,
            altitudeRelativeTakeoffM = 20.0,
            takeoffAltitudeAmslM = 100.0,
            rtk = RtkTelemetryState(
                enabled = true,
                connected = true,
                healthy = true,
                fix = RtkFix.FIXED,
                fusedLatitudeDeg = 49.00001,
                fusedLongitudeDeg = 8.00001,
                fusedAltitudeM = 121.0
            )
        )

        assertEquals(PositionSource.RTK_FUSED, result.source)
        assertEquals(49.00001, result.latitudeDeg, 0.0000001)
        assertEquals(8.00001, result.longitudeDeg, 0.0000001)
        assertEquals(120.0, result.altitudeAmslM, 0.001)
    }

    @Test
    fun staleOrDisconnectedRtkFallsBackToFlightController() {
        for (rtk in listOf(
            RtkTelemetryState(
                enabled = true, connected = true, healthy = true, fix = RtkFix.STALE,
                fusedLatitudeDeg = 49.1, fusedLongitudeDeg = 8.1
            ),
            RtkTelemetryState(
                enabled = true, connected = false, healthy = true, fix = RtkFix.FIXED,
                fusedLatitudeDeg = 49.1, fusedLongitudeDeg = 8.1
            )
        )) {
            val result = PositionResolver.resolve(
                49.0, 8.0, 120.0, 20.0, 100.0, rtk
            )
            assertEquals(PositionSource.FLIGHT_CONTROLLER, result.source)
            assertEquals(49.0, result.latitudeDeg, 0.0)
            assertEquals(8.0, result.longitudeDeg, 0.0)
        }
    }

    @Test
    fun amslPrefersTakeoffAltitudePlusRelativeAltitude() {
        val result = PositionResolver.resolve(
            49.0, 8.0, 999.0, 72.5, 113.25, RtkTelemetryState()
        )
        assertEquals(185.75, result.altitudeAmslM, 0.001)
        assertEquals(72.5, result.altitudeRelativeTakeoffM, 0.001)
    }

    @Test
    fun amslFallsBackToFlightControllerAltitudeWhenTakeoffAltitudeUnavailable() {
        val result = PositionResolver.resolve(
            49.0, 8.0, 143.4, 72.5, null, RtkTelemetryState()
        )
        assertEquals(143.4, result.altitudeAmslM, 0.001)
    }
}
