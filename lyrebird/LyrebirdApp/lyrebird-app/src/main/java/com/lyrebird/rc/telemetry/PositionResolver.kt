package com.lyrebird.rc.telemetry

internal enum class PositionSource {
    FLIGHT_CONTROLLER,
    RTK_FUSED
}

internal data class ResolvedAircraftPosition(
    val latitudeDeg: Double,
    val longitudeDeg: Double,
    val altitudeAmslM: Double,
    val altitudeRelativeTakeoffM: Double,
    val source: PositionSource
)

/**
 * Selects the position that should represent the aircraft to a ground station.
 *
 * Horizontal RTK fusion is used only for a fresh, connected and healthy FLOAT/FIXED solution.
 * Vertical MAVLink altitude remains on the FC/take-off reference path because DJI documents
 * real3DLocation as fused position but does not expose enough reference metadata here to prove
 * that its altitude can be mixed with HOME_POSITION AMSL without an offset.
 */
internal object PositionResolver {
    fun resolve(
        flightControllerLatitudeDeg: Double,
        flightControllerLongitudeDeg: Double,
        flightControllerAltitudeM: Double?,
        altitudeRelativeTakeoffM: Double,
        takeoffAltitudeAmslM: Double?,
        rtk: RtkTelemetryState
    ): ResolvedAircraftPosition {
        val useRtk = rtk.enabled &&
            rtk.connected &&
            rtk.healthy &&
            (rtk.fix == RtkFix.FLOAT || rtk.fix == RtkFix.FIXED) &&
            validCoordinate(rtk.fusedLatitudeDeg, rtk.fusedLongitudeDeg)

        val latitude = if (useRtk) rtk.fusedLatitudeDeg!! else flightControllerLatitudeDeg
        val longitude = if (useRtk) rtk.fusedLongitudeDeg!! else flightControllerLongitudeDeg

        val amsl = when {
            takeoffAltitudeAmslM?.isFinite() == true && altitudeRelativeTakeoffM.isFinite() ->
                takeoffAltitudeAmslM + altitudeRelativeTakeoffM
            flightControllerAltitudeM?.isFinite() == true -> flightControllerAltitudeM
            else -> 0.0
        }

        return ResolvedAircraftPosition(
            latitudeDeg = latitude,
            longitudeDeg = longitude,
            altitudeAmslM = amsl,
            altitudeRelativeTakeoffM = altitudeRelativeTakeoffM.takeIf { it.isFinite() } ?: 0.0,
            source = if (useRtk) PositionSource.RTK_FUSED else PositionSource.FLIGHT_CONTROLLER
        )
    }

    private fun validCoordinate(latitude: Double?, longitude: Double?): Boolean =
        latitude != null &&
            longitude != null &&
            latitude.isFinite() &&
            longitude.isFinite() &&
            latitude in -90.0..90.0 &&
            longitude in -180.0..180.0 &&
            (latitude != 0.0 || longitude != 0.0)
}
