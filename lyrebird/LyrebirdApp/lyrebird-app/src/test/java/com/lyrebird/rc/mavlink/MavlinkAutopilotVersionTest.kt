package com.lyrebird.rc.mavlink

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MavlinkAutopilotVersionTest {

    @Test
    fun advertisedCapabilitiesMatchImplementedMavlinkServices() {
        val payload = MavlinkMessages.autopilotVersion()
        val capabilities = ByteBuffer.wrap(payload)
            .order(ByteOrder.LITTLE_ENDIAN)
            .getLong(0)

        assertTrue((capabilities and Mav.CAP_MAVLINK2) != 0L)
        assertTrue((capabilities and Mav.CAP_MISSION_INT) != 0L)
        assertTrue((capabilities and Mav.CAP_COMMAND_INT) != 0L)
        assertTrue((capabilities and Mav.CAP_FTP) != 0L)
        assertEquals(
            Mav.CAP_MAVLINK2 or Mav.CAP_MISSION_INT or Mav.CAP_COMMAND_INT or Mav.CAP_FTP,
            capabilities
        )
    }
}
