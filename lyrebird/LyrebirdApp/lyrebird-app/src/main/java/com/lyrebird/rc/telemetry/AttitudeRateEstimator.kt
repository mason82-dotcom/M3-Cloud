package com.lyrebird.rc.telemetry

import kotlin.math.PI

internal data class AttitudeRates(
    val rollRadS: Double = 0.0,
    val pitchRadS: Double = 0.0,
    val yawRadS: Double = 0.0
)

/**
 * Derives body-angle rates from successive DJI attitude samples.
 *
 * MSDK 5.18 exposes aircraft Euler attitude in the telemetry path used by Lyrebird, but no direct
 * roll/pitch/yaw-rate key is wired here. MAVLink ATTITUDE nevertheless requires all three rates.
 * Returning literal zero while the aircraft rotates is worse than a bounded derivative, so this
 * estimator differentiates the actual samples with angle wrapping and a small low-pass filter.
 */
internal class AttitudeRateEstimator(
    private val monotonicNs: () -> Long = System::nanoTime,
    private val minSampleNs: Long = 10_000_000L,
    private val maxSampleNs: Long = 1_000_000_000L,
    private val alpha: Double = 0.35
) {
    private data class Sample(
        val rollDeg: Double,
        val pitchDeg: Double,
        val yawDeg: Double,
        val timeNs: Long
    )

    private var previous: Sample? = null
    private var filtered = AttitudeRates()

    @Synchronized
    fun update(
        rollDeg: Double,
        pitchDeg: Double,
        yawDeg: Double
    ): AttitudeRates {
        if (!rollDeg.isFinite() || !pitchDeg.isFinite() || !yawDeg.isFinite()) {
            previous = null
            filtered = AttitudeRates()
            return filtered
        }

        val now = monotonicNs()
        val current = Sample(rollDeg, pitchDeg, yawDeg, now)
        val old = previous
        if (old == null) {
            previous = current
            return filtered
        }

        val dtNs = now - old.timeNs
        if (dtNs < minSampleNs) {
            return filtered
        }
        if (dtNs > maxSampleNs) {
            previous = current
            filtered = AttitudeRates()
            return filtered
        }

        val dtS = dtNs / 1_000_000_000.0
        val raw = AttitudeRates(
            rollRadS = Math.toRadians(wrapDeltaDeg(rollDeg - old.rollDeg)) / dtS,
            pitchRadS = Math.toRadians(wrapDeltaDeg(pitchDeg - old.pitchDeg)) / dtS,
            yawRadS = Math.toRadians(wrapDeltaDeg(yawDeg - old.yawDeg)) / dtS
        )
        filtered = AttitudeRates(
            rollRadS = blend(filtered.rollRadS, raw.rollRadS),
            pitchRadS = blend(filtered.pitchRadS, raw.pitchRadS),
            yawRadS = blend(filtered.yawRadS, raw.yawRadS)
        )
        previous = current
        return filtered
    }

    private fun blend(previous: Double, current: Double): Double =
        previous + alpha.coerceIn(0.0, 1.0) * (current - previous)

    private fun wrapDeltaDeg(value: Double): Double {
        var wrapped = value % 360.0
        if (wrapped > 180.0) wrapped -= 360.0
        if (wrapped < -180.0) wrapped += 360.0
        return wrapped
    }
}
