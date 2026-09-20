package com.lyrebird.rc.mavlink

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertEquals
import org.junit.Test

class MavlinkAltitudeTest {

    @Test
    fun altitudeUsesCanonicalWireLayout() {
        val payload = MavlinkMessages.altitude(
            MavlinkSnapshot(
                altitudeAslM = 143.25,
                altitudeAglM = 72.50
            ),
            timeUsec = 1_234_567L
        )

        assertEquals(32, payload.size)

        val fields = ByteBuffer.wrap(payload).order(ByteOrder.LITTLE_ENDIAN)
        assertEquals(1_234_567L, fields.long)
        assertEquals(72.50f, fields.float, 0.001f)
        assertEquals(143.25f, fields.float, 0.001f)
        assertEquals(72.50f, fields.float, 0.001f)
        assertEquals(72.50f, fields.float, 0.001f)
        assertEquals(-1001.0f, fields.float, 0.001f)
        assertEquals(-1.0f, fields.float, 0.001f)
    }

    @Test
    fun altitudeUsesCanonicalMessageIdAndCrcExtra() {
        assertEquals(141, MavlinkMsgId.ALTITUDE)
        assertEquals(47, MavlinkCrc.CRC_EXTRA[MavlinkMsgId.ALTITUDE])
    }
}
