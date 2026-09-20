package com.lyrebird.rc.mavlink

import com.lyrebird.rc.telemetry.RtkFix
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertEquals
import org.junit.Test

class MavlinkPositionTest {

    private fun gpsFields(snapshot: MavlinkSnapshot): ByteBuffer =
        ByteBuffer.wrap(MavlinkMessages.gpsRawInt(snapshot, 1L))
            .order(ByteOrder.LITTLE_ENDIAN)

    @Test
    fun gpsRawCourseOverGroundComesFromVelocityNotHeading() {
        val payload = gpsFields(
            MavlinkSnapshot(
                velocityNorthMps = 0.0,
                velocityEastMps = 5.0,
                headingDeg = 12.0,
                satelliteCount = 10,
                gnssSignalLevel = "LEVEL_4"
            )
        )
        assertEquals(9000, payload.getShort(26).toInt() and 0xFFFF)
    }

    @Test
    fun gpsRawCourseIsUnknownWhenStationary() {
        val payload = gpsFields(
            MavlinkSnapshot(
                velocityNorthMps = 0.0,
                velocityEastMps = 0.0,
                headingDeg = 270.0
            )
        )
        assertEquals(0xFFFF, payload.getShort(26).toInt() and 0xFFFF)
    }

    @Test
    fun unknownSatelliteCountUsesMavlinkUnknownSentinel() {
        val payload = gpsFields(MavlinkSnapshot(satelliteCount = -1))
        assertEquals(255, payload.get(29).toInt() and 0xFF)
    }

    @Test
    fun gpsSignalLevelControlsNormalGnssFix() {
        assertEquals(3, MavlinkMessages.gnssFixType("LEVEL_3", 4))
        assertEquals(0, MavlinkMessages.gnssFixType("LEVEL_2", 20))
        assertEquals(3, MavlinkMessages.gnssFixType("UNKNOWN", 8))
    }

    @Test
    fun rtkFixRequiresEnabledConnectedHealthyState() {
        val fixed = MavlinkSnapshot(
            rtkEnabled = true,
            rtkConnected = true,
            rtkHealthy = true,
            rtkFix = RtkFix.FIXED,
            gnssSignalLevel = "LEVEL_4"
        )
        assertEquals(6, MavlinkMessages.gpsFixType(fixed))
        assertEquals(3, MavlinkMessages.gpsFixType(fixed.copy(rtkConnected = false)))
    }

    @Test
    fun homePositionRequiresSdkHomeSetStateAndValidCoordinates() {
        val coordinatesOnly = MavlinkSnapshot(
            homeLatitudeDeg = 49.0,
            homeLongitudeDeg = 8.0,
            homeSet = false
        )
        assertEquals(false, coordinatesOnly.homePositionValid)
        assertEquals(true, coordinatesOnly.copy(homeSet = true).homePositionValid)
    }
}
