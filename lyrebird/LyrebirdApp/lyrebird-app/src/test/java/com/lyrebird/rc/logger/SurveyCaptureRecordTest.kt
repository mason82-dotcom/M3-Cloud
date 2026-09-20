package com.lyrebird.rc.logger

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SurveyCaptureRecordTest {

    private fun record(
        mediaIndex: Int? = 184,
        rtkAgeMs: Long = 183,
        stdAltitude: Double? = 0.026
    ) = SurveyCaptureRecord(
        eventEpochMs = 1_789_738_938_481L,
        mediaIndex = mediaIndex,
        lens = "WIDE",
        latitudeDeg = 49.12345678,
        longitudeDeg = 8.65432109,
        altitudeAslM = 143.278,
        altitudeAglM = 72.43,
        satelliteCount = 29,
        headingDeg = 132.7,
        aircraftRollDeg = -0.7,
        aircraftPitchDeg = 1.2,
        aircraftYawDeg = 132.6,
        gimbalRollDeg = 0.1,
        gimbalPitchDeg = -89.8,
        gimbalYawDeg = 132.5,
        gimbalJointRollDeg = 0.0,
        gimbalJointPitchDeg = -89.9,
        gimbalJointYawDeg = 0.1,
        rtkEnabled = true,
        rtkHealthy = true,
        rtkFix = "FIXED",
        rtkRawFix = "FIXED",
        rtkAgeMs = rtkAgeMs,
        rtkLatitudeDeg = 49.12345679,
        rtkLongitudeDeg = 8.65432110,
        rtkAltitudeM = 143.281,
        rtkStdLatitudeM = 0.014,
        rtkStdLongitudeM = 0.012,
        rtkStdAltitudeM = stdAltitude,
        rtkSource = "CUSTOM_NETWORK_SERVICE",
        flightMode = "WAYPOINT"
    )

    @Test
    fun recordKeepsFlightAndRawRtkPositionsSeparate() {
        val fields = record().toLogFields()

        assertEquals(49.12345678, fields["latitude"])
        assertEquals(49.12345679, fields["rtkLatitude"])
        assertEquals("FIXED", fields["rtkFix"])
        assertEquals(183L, fields["rtkAgeMs"])
        assertEquals("WIDE", fields["lens"])
    }

    @Test
    fun unknownOptionalValuesAreOmittedRatherThanFabricated() {
        val fields = record(
            mediaIndex = null,
            rtkAgeMs = Long.MAX_VALUE,
            stdAltitude = null
        ).toLogFields()

        assertFalse(fields.containsKey("mediaIndex"))
        assertFalse(fields.containsKey("rtkAgeMs"))
        assertFalse(fields.containsKey("rtkStdAltitudeM"))
        assertTrue(fields.containsKey("rtkFix"))
    }
}
