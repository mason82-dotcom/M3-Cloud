package com.lyrebird.rc.mavlink

import com.lyrebird.rc.telemetry.RtkFix
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertEquals
import org.junit.Test

class MavlinkRtkFixTest {

    private fun fixType(snapshot: MavlinkSnapshot): Int {
        val payload = MavlinkMessages.gpsRawInt(snapshot, timeUsec = 1L)
        // GPS_RAW_INT wire offset 28 is fix_type.
        return ByteBuffer.wrap(payload)
            .order(ByteOrder.LITTLE_ENDIAN)
            .get(28)
            .toInt() and 0xFF
    }

    @Test
    fun healthyFixedRtkIsReportedAsMavlinkRtkFixed() {
        assertEquals(
            6,
            fixType(
                MavlinkSnapshot(
                    satelliteCount = 20,
                    rtkEnabled = true,
                    rtkConnected = true,
                    rtkHealthy = true,
                    rtkFix = RtkFix.FIXED
                )
            )
        )
    }

    @Test
    fun healthyFloatRtkIsReportedAsMavlinkRtkFloat() {
        assertEquals(
            5,
            fixType(
                MavlinkSnapshot(
                    satelliteCount = 20,
                    rtkEnabled = true,
                    rtkConnected = true,
                    rtkHealthy = true,
                    rtkFix = RtkFix.FLOAT
                )
            )
        )
    }

    @Test
    fun staleRtkFallsBackToNormalGnssFix() {
        assertEquals(
            3,
            fixType(
                MavlinkSnapshot(
                    satelliteCount = 20,
                    rtkEnabled = true,
                    rtkConnected = true,
                    rtkHealthy = true,
                    rtkFix = RtkFix.STALE
                )
            )
        )
    }

    @Test
    fun unhealthyRtkFallsBackToNormalGnssFix() {
        assertEquals(
            3,
            fixType(
                MavlinkSnapshot(
                    satelliteCount = 20,
                    rtkEnabled = true,
                    rtkConnected = true,
                    rtkHealthy = false,
                    rtkFix = RtkFix.FIXED
                )
            )
        )
    }
}
