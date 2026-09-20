package com.lyrebird.rc.logger

/**
 * State frozen at the camera's actual newly-generated-media event.
 *
 * The flight-controller position and raw RTK mobile-station position are both retained on
 * purpose. They answer different questions and must not be silently substituted for one another.
 */
internal data class SurveyCaptureRecord(
    val eventEpochMs: Long,
    val mediaIndex: Int?,
    val lens: String,

    val latitudeDeg: Double,
    val longitudeDeg: Double,
    val altitudeAslM: Double,
    val altitudeAglM: Double,
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
    val rtkHealthy: Boolean,
    val rtkFix: String,
    val rtkRawFix: String,
    val rtkAgeMs: Long,
    val rtkLatitudeDeg: Double?,
    val rtkLongitudeDeg: Double?,
    val rtkAltitudeM: Double?,
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
        put("rtkHealthy", rtkHealthy)
        put("rtkFix", rtkFix)
        put("rtkRawFix", rtkRawFix)
        if (rtkAgeMs != Long.MAX_VALUE) put("rtkAgeMs", rtkAgeMs)
        rtkLatitudeDeg?.let { put("rtkLatitude", it) }
        rtkLongitudeDeg?.let { put("rtkLongitude", it) }
        rtkAltitudeM?.let { put("rtkAltitudeM", it) }
        rtkStdLatitudeM?.let { put("rtkStdLatitudeM", it) }
        rtkStdLongitudeM?.let { put("rtkStdLongitudeM", it) }
        rtkStdAltitudeM?.let { put("rtkStdAltitudeM", it) }
        put("rtkSource", rtkSource)

        put("flightMode", flightMode)
    }
}
