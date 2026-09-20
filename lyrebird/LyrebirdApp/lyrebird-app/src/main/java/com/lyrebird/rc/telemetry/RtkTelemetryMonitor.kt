package com.lyrebird.rc.telemetry

import dji.sdk.keyvalue.value.rtkmobilestation.RTKPositioningSolution
import dji.v5.manager.aircraft.rtk.RTKCenter
import dji.v5.manager.aircraft.rtk.RTKLocationInfoListener
import dji.v5.manager.aircraft.rtk.RTKSystemStateListener

/** SDK-free RTK fix state consumed by telemetry/MAVLink code. */
internal enum class RtkFix {
    NONE,
    SINGLE,
    FLOAT,
    FIXED,
    UNKNOWN,
    STALE
}

/**
 * One immutable RTK read.
 *
 * [rawFix] is the last solution DJI reported. [fix] additionally accounts for freshness, so a
 * seconds-old FIXED_POINT cannot remain green forever after RTK updates stop.
 */
internal data class RtkTelemetryState(
    val enabled: Boolean = false,
    val healthy: Boolean = false,
    val fix: RtkFix = RtkFix.UNKNOWN,
    val rawFix: RtkFix = RtkFix.UNKNOWN,
    val latitudeDeg: Double? = null,
    val longitudeDeg: Double? = null,
    val altitudeM: Double? = null,
    val stdLatitudeM: Double? = null,
    val stdLongitudeM: Double? = null,
    val stdAltitudeM: Double? = null,
    val source: String = "UNKNOWN",
    val ageMs: Long = Long.MAX_VALUE
)

/**
 * Process-scoped bridge from DJI RTKCenter callbacks to a plain immutable state.
 *
 * No LiveData/ViewModel dependency: FlightDeck needs RTK even when the RTK settings fragment was
 * never opened. The clock is monotonic, so wall-clock corrections on the RC cannot make a stale
 * fix look fresh again.
 */
internal class RtkTelemetryMonitor(
    private val staleAfterMs: Long = DEFAULT_STALE_AFTER_MS,
    private val monotonicMs: () -> Long = { System.nanoTime() / 1_000_000L }
) {
    private data class RawState(
        val enabled: Boolean = false,
        val healthy: Boolean = false,
        val fix: RtkFix = RtkFix.UNKNOWN,
        val latitudeDeg: Double? = null,
        val longitudeDeg: Double? = null,
        val altitudeM: Double? = null,
        val stdLatitudeM: Double? = null,
        val stdLongitudeM: Double? = null,
        val stdAltitudeM: Double? = null,
        val source: String = "UNKNOWN",
        val locationUpdatedAtMs: Long = 0L
    )

    @Volatile
    private var raw = RawState()

    @Volatile
    private var started = false

    private val locationListener = RTKLocationInfoListener { info ->
        val location = info.rtkLocation
        val mobile = location?.mobileStationLocation
        raw = raw.copy(
            fix = mapFix(location?.positioningSolution),
            latitudeDeg = mobile?.latitude,
            longitudeDeg = mobile?.longitude,
            altitudeM = mobile?.altitude,
            stdLatitudeM = location?.stdLatitude,
            stdLongitudeM = location?.stdLongitude,
            stdAltitudeM = location?.stdAltitude,
            locationUpdatedAtMs = monotonicMs()
        )
    }

    private val systemListener = RTKSystemStateListener { state ->
        raw = raw.copy(
            enabled = state.isRTKEnabled,
            healthy = state.rtkHealthy,
            source = state.rtkReferenceStationSource?.name ?: "UNKNOWN"
        )
    }

    @Synchronized
    fun start() {
        if (started) return
        RTKCenter.getInstance().addRTKLocationInfoListener(locationListener)
        RTKCenter.getInstance().addRTKSystemStateListener(systemListener)
        started = true
    }

    @Synchronized
    fun stop() {
        if (!started) return
        RTKCenter.getInstance().removeRTKLocationInfoListener(locationListener)
        RTKCenter.getInstance().removeRTKSystemStateListener(systemListener)
        started = false
    }

    fun snapshot(): RtkTelemetryState {
        val current = raw
        val age = if (current.locationUpdatedAtMs == 0L) {
            Long.MAX_VALUE
        } else {
            (monotonicMs() - current.locationUpdatedAtMs).coerceAtLeast(0L)
        }
        val effectiveFix = when {
            age > staleAfterMs &&
                (current.fix == RtkFix.FIXED || current.fix == RtkFix.FLOAT) -> RtkFix.STALE
            else -> current.fix
        }
        return RtkTelemetryState(
            enabled = current.enabled,
            healthy = current.healthy,
            fix = effectiveFix,
            rawFix = current.fix,
            latitudeDeg = current.latitudeDeg,
            longitudeDeg = current.longitudeDeg,
            altitudeM = current.altitudeM,
            stdLatitudeM = current.stdLatitudeM,
            stdLongitudeM = current.stdLongitudeM,
            stdAltitudeM = current.stdAltitudeM,
            source = current.source,
            ageMs = age
        )
    }

    private fun mapFix(solution: RTKPositioningSolution?): RtkFix = when (solution) {
        RTKPositioningSolution.NONE -> RtkFix.NONE
        RTKPositioningSolution.SINGLE_POINT -> RtkFix.SINGLE
        RTKPositioningSolution.FLOAT -> RtkFix.FLOAT
        RTKPositioningSolution.FIXED_POINT -> RtkFix.FIXED
        RTKPositioningSolution.UNKNOWN, null -> RtkFix.UNKNOWN
        else -> RtkFix.UNKNOWN
    }

    private companion object {
        const val DEFAULT_STALE_AFTER_MS = 3_000L
    }
}
