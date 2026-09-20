package com.lyrebird.rc.logger

/**
 * State frozen at the camera's actual newly-generated-media event.
 *
 * The resolved navigation position, raw flight-controller position, raw RTK mobile-station
 * position and DJI real3DLocation are retained separately on purpose. They answer different
 * questions and must not be silently substituted for one another.
 */
internal data class SurveyCaptureRecord(
    val eventEpochMs: Long,
    val mediaIndex: Int?,
    val lens: String,

    /** Position actually exported to MAVLink after position resolution. */
    val latitudeDeg: Double,
    val longitudeDeg: Double,
    val altitudeAslM: Double,
    val altitudeAglM: Double,
    val positionSource: String,
    /** Raw flight-controller position sampled at the same capture event. */
    val flightControllerLatitudeDeg: Double,
    val flightControllerLongitudeDeg: Double,
    val flightControllerAltitudeM: Double?,
    val satelliteCount: Int,

    val headingDeg: Double,
    val aircraftRollDeg: Double,
    val aircraftPitchDeg: Double,
    val aircraftYawDeg: Double,

    val gimbalRollDeg: Double,
    val gimbalPitchDeg: Double,
    val gimbalYawDeg: Double,
    val gimbalJointRollDeg: Double,
    val gimbalJointPitchDeg: Double,
    val gimbalJointYawDeg: Double,

    val rtkEnabled: Boolean,
    val rtkConnected: Boolean,
    val rtkHealthy: Boolean,
    val rtkFix: String,
    val rtkRawFix: String,
    val rtkAgeMs: Long,
    /** Raw mobile-station/antenna RTK position. */
    val rtkLatitudeDeg: Double?,
    val rtkLongitudeDeg: Double?,
    val rtkAltitudeM: Double?,
    /** DJI RTKLocationInfo.real3DLocation, kept separate from the raw antenna fix. */
    val rtkFusedLatitudeDeg: Double?,
    val rtkFusedLongitudeDeg: Double?,
    val rtkFusedAltitudeM: Double?,
    val rtkStdLatitudeM: Double?,
    val rtkStdLongitudeM: Double?,
    val rtkStdAltitudeM: Double?,
    val rtkSource: String,

    val flightMode: String
) {
    fun toLogFields(): Map<String, Any> = linkedMapOf<String, Any>().apply {
        mediaIndex?.let { put("mediaIndex", it) }
        put("lens", lens)

        put("latitude", latitudeDeg)
        put("longitude", longitudeDeg)
        put("altitudeAslM", altitudeAslM)
        put("altitudeAglM", altitudeAglM)
        put("positionSource", positionSource)
        put("flightControllerLatitude", flightControllerLatitudeDeg)
        put("flightControllerLongitude", flightControllerLongitudeDeg)
        flightControllerAltitudeM?.let { put("flightControllerAltitudeM", it) }
        put("satellites", satelliteCount)

        put("headingDeg", headingDeg)
        put("aircraftRollDeg", aircraftRollDeg)
        put("aircraftPitchDeg", aircraftPitchDeg)
        put("aircraftYawDeg", aircraftYawDeg)

        put("gimbalRollDeg", gimbalRollDeg)
        put("gimbalPitchDeg", gimbalPitchDeg)
        put("gimbalYawDeg", gimbalYawDeg)
        put("gimbalJointRollDeg", gimbalJointRollDeg)
        put("gimbalJointPitchDeg", gimbalJointPitchDeg)
        put("gimbalJointYawDeg", gimbalJointYawDeg)

        put("rtkEnabled", rtkEnabled)
        put("rtkConnected", rtkConnected)
        put("rtkHealthy", rtkHealthy)
        put("rtkFix", rtkFix)
        put("rtkRawFix", rtkRawFix)
        if (rtkAgeMs != Long.MAX_VALUE) put("rtkAgeMs", rtkAgeMs)
        rtkLatitudeDeg?.let { put("rtkLatitude", it) }
        rtkLongitudeDeg?.let { put("rtkLongitude", it) }
        rtkAltitudeM?.let { put("rtkAltitudeM", it) }
        rtkFusedLatitudeDeg?.let { put("rtkFusedLatitude", it) }
        rtkFusedLongitudeDeg?.let { put("rtkFusedLongitude", it) }
        rtkFusedAltitudeM?.let { put("rtkFusedAltitudeM", it) }
        rtkStdLatitudeM?.let { put("rtkStdLatitudeM", it) }
        rtkStdLongitudeM?.let { put("rtkStdLongitudeM", it) }
        rtkStdAltitudeM?.let { put("rtkStdAltitudeM", it) }
        put("rtkSource", rtkSource)

        put("flightMode", flightMode)
    }
}
