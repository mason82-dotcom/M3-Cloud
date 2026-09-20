package com.lyrebird.rc.mavlink

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertEquals
import org.junit.Test

class MavlinkRcChannelsTest {

    @Test
    fun rcChannelsUsesCanonicalMessageDefinition() {
        assertEquals(65, MavlinkMsgId.RC_CHANNELS)
        assertEquals(118, MavlinkCrc.CRC_EXTRA[MavlinkMsgId.RC_CHANNELS])
        assertEquals(
            42,
            MavlinkMessages.rcChannels(MavlinkSnapshot(), timeBootMs = 1L).size
        )
    }

    @Test
    fun physicalDjiSticksMapLinearlyToPwmRange() {
        assertEquals(1000, MavlinkMessages.rcStickToPwm(-660))
        assertEquals(1500, MavlinkMessages.rcStickToPwm(0))
        assertEquals(2000, MavlinkMessages.rcStickToPwm(660))
        assertEquals(1000, MavlinkMessages.rcStickToPwm(-999))
        assertEquals(2000, MavlinkMessages.rcStickToPwm(999))
    }

    @Test
    fun connectedControllerPublishesFourPhysicalChannelsAndScaledAirlinkQuality() {
        val payload = ByteBuffer.wrap(
            MavlinkMessages.rcChannels(
                MavlinkSnapshot(
                    rcConnected = true,
                    rcStickLeftHorizontal = -660,
                    rcStickLeftVertical = 0,
                    rcStickRightHorizontal = 330,
                    rcStickRightVertical = 660,
                    airLinkConnected = true,
                    airLinkQualityPercent = 50
                ),
                timeBootMs = 123L
            )
        ).order(ByteOrder.LITTLE_ENDIAN)

        assertEquals(123L, payload.getInt(0).toLong() and 0xFFFFFFFFL)
        assertEquals(1000, payload.getShort(4).toInt() and 0xFFFF)
        assertEquals(1500, payload.getShort(6).toInt() and 0xFFFF)
        assertEquals(1750, payload.getShort(8).toInt() and 0xFFFF)
        assertEquals(2000, payload.getShort(10).toInt() and 0xFFFF)
        assertEquals(0xFFFF, payload.getShort(12).toInt() and 0xFFFF)
        assertEquals(4, payload.get(40).toInt() and 0xFF)
        assertEquals(127, payload.get(41).toInt() and 0xFF)
    }

    @Test
    fun disconnectedControllerPublishesNoChannelsAndUnknownRssi() {
        val payload = ByteBuffer.wrap(
            MavlinkMessages.rcChannels(MavlinkSnapshot(), timeBootMs = 0L)
        ).order(ByteOrder.LITTLE_ENDIAN)

        assertEquals(0xFFFF, payload.getShort(4).toInt() and 0xFFFF)
        assertEquals(0, payload.get(40).toInt() and 0xFF)
        assertEquals(255, payload.get(41).toInt() and 0xFF)
    }
}
