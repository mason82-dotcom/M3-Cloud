package com.lyrebird.rc.telemetry

import kotlin.math.PI
import org.junit.Assert.assertEquals
import org.junit.Test

class AttitudeRateEstimatorTest {

    @Test
    fun derivesRatesFromSuccessiveSamples() {
        var now = 0L
        val estimator = AttitudeRateEstimator(
            monotonicNs = { now },
            alpha = 1.0
        )

        estimator.update(0.0, 0.0, 0.0)
        now = 100_000_000L
        val rates = estimator.update(9.0, -3.0, 18.0)

        assertEquals(Math.toRadians(90.0), rates.rollRadS, 1e-9)
        assertEquals(Math.toRadians(-30.0), rates.pitchRadS, 1e-9)
        assertEquals(Math.toRadians(180.0), rates.yawRadS, 1e-9)
    }

    @Test
    fun yawWrapUsesShortestAngularDelta() {
        var now = 0L
        val estimator = AttitudeRateEstimator(
            monotonicNs = { now },
            alpha = 1.0
        )

        estimator.update(0.0, 0.0, 179.0)
        now = 100_000_000L
        val rates = estimator.update(0.0, 0.0, -179.0)

        assertEquals(Math.toRadians(20.0), rates.yawRadS, 1e-9)
    }

    @Test
    fun tooFastPollDoesNotAdvanceDerivativeBaseline() {
        var now = 0L
        val estimator = AttitudeRateEstimator(
            monotonicNs = { now },
            alpha = 1.0
        )

        estimator.update(0.0, 0.0, 0.0)
        now = 5_000_000L
        assertEquals(0.0, estimator.update(0.0, 0.0, 1.0).yawRadS, 0.0)

        now = 100_000_000L
        assertEquals(
            Math.toRadians(10.0),
            estimator.update(0.0, 0.0, 1.0).yawRadS,
            1e-9
        )
    }

    @Test
    fun longGapResetsInsteadOfInventingRate() {
        var now = 0L
        val estimator = AttitudeRateEstimator(
            monotonicNs = { now },
            alpha = 1.0
        )

        estimator.update(0.0, 0.0, 0.0)
        now = 2_000_000_000L
        val rates = estimator.update(30.0, 10.0, 40.0)

        assertEquals(0.0, rates.rollRadS, 0.0)
        assertEquals(0.0, rates.pitchRadS, 0.0)
        assertEquals(0.0, rates.yawRadS, 0.0)
    }
}
