package com.lyrebird.rc.mavlink

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * GIMBAL_DEVICE_ATTITUDE_STATUS encoding.
 *
 * DJI's world-frame attitude is sent as an earth-frame quaternion. The mechanical joint yaw is
 * intentionally not reused as MAVLink delta_yaw; until the exact frame transform is proven, the
 * standards-compliant value is NaN.
 */
class MavlinkGimbalMessageTest {

    @Test
    fun worldAttitudeIsAdvertisedInEarthFrame() {
        val payload = MavlinkMessages.gimbalDeviceAttitudeStatus(
            MavlinkSnapshot(
                gimbalTelemetryValid = true,
                gimbalRollDeg = 0.0,
                gimbalPitchDeg = -45.0,
                gimbalYawDeg = 30.0,
                gimbalJointYawDeg = 12.0
            ),
            timeBootMs = 1234L
        )
        val fields = ByteBuffer.wrap(payload).order(ByteOrder.LITTLE_ENDIAN)

        assertEquals(64, fields.getShort(36).toInt() and 0xFFFF)
        assertTrue(fields.getFloat(40).isNaN())
    }

    @Test
    fun jointYawDoesNotLeakIntoDeltaYaw() {
        val a = MavlinkMessages.gimbalDeviceAttitudeStatus(
            MavlinkSnapshot(gimbalTelemetryValid = true, gimbalJointYawDeg = -90.0),
            1L
        )
        val b = MavlinkMessages.gimbalDeviceAttitudeStatus(
            MavlinkSnapshot(gimbalTelemetryValid = true, gimbalJointYawDeg = 90.0),
            1L
        )

        assertTrue(ByteBuffer.wrap(a).order(ByteOrder.LITTLE_ENDIAN).getFloat(40).isNaN())
        assertTrue(ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).getFloat(40).isNaN())
    }
}
