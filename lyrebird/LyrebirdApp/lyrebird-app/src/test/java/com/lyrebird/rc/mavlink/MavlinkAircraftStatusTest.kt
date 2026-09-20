package com.lyrebird.rc.mavlink

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertEquals
import org.junit.Test

class MavlinkAircraftStatusTest {

    @Test
    fun extendedStateUsesUndefinedVtolAndActualFlyingState() {
        val payload = MavlinkMessages.extendedSysState(
            MavlinkSnapshot(motorsRunning = true, isFlying = false, flightMode = "UNKNOWN")
        )
        assertEquals(Mav.VTOL_STATE_UNDEFINED, payload[0].toInt() and 0xFF)
        assertEquals(Mav.LANDED_STATE_ON_GROUND, payload[1].toInt() and 0xFF)

        val airborne = MavlinkMessages.extendedSysState(
            MavlinkSnapshot(motorsRunning = true, isFlying = true, flightMode = "GPS_NORMAL")
        )
        assertEquals(Mav.LANDED_STATE_IN_AIR, airborne[1].toInt() and 0xFF)
    }

    @Test
    fun sysStatusCarriesRealBatteryVoltageAndConvertedDischargeCurrent() {
        val payload = ByteBuffer.wrap(
            MavlinkMessages.sysStatus(
                MavlinkSnapshot(
                    flightControllerConnected = true,
                    batteryConnected = true,
                    batteryPercent = 71,
                    batteryVoltageMv = 15432,
                    batteryCurrentMa = -1230,
                    compassHealthy = true,
                    gnssSignalLevel = "LEVEL_4"
                )
            )
        ).order(ByteOrder.LITTLE_ENDIAN)

        assertEquals(15432, payload.getShort(14).toInt() and 0xFFFF)
        assertEquals(123, payload.getShort(16).toInt())
        assertEquals(71, payload.get(30).toInt())
    }

    @Test
    fun unknownSysStatusBatteryVoltageUsesMavlinkSentinel() {
        val payload = ByteBuffer.wrap(MavlinkMessages.sysStatus(MavlinkSnapshot()))
            .order(ByteOrder.LITTLE_ENDIAN)
        assertEquals(0xFFFF, payload.getShort(14).toInt() and 0xFFFF)
        assertEquals(-1, payload.getShort(16).toInt())
    }

    @Test
    fun batteryStatusCarriesTemperatureCellsCurrentAndCapacityConsumption() {
        val payload = ByteBuffer.wrap(
            MavlinkMessages.batteryStatus(
                MavlinkSnapshot(
                    batteryConnected = true,
                    batteryPercent = 80,
                    batteryCurrentMa = -2500,
                    batteryTemperatureC = 31.25,
                    batteryChargeRemainingMah = 4000,
                    batteryFullChargeCapacityMah = 5000,
                    batteryCellVoltagesMv = listOf(3860, 3855, 3862, 3858),
                    remainingFlightTimeS = 900
                )
            )
        ).order(ByteOrder.LITTLE_ENDIAN)

        assertEquals(1000, payload.getInt(0))
        assertEquals(3125, payload.getShort(8).toInt())
        assertEquals(3860, payload.getShort(10).toInt() and 0xFFFF)
        assertEquals(3855, payload.getShort(12).toInt() and 0xFFFF)
        assertEquals(0xFFFF, payload.getShort(18).toInt() and 0xFFFF)
        assertEquals(250, payload.getShort(30).toInt())
        assertEquals(80, payload.get(35).toInt())
        assertEquals(900, payload.getInt(36))
    }

    @Test
    fun heartbeatReportsCriticalDuringDjiFailsafe() {
        val payload = MavlinkMessages.heartbeat(
            MavlinkSnapshot(
                flightControllerConnected = true,
                isFailsafe = true,
                flightMode = "GPS_NORMAL"
            )
        )
        assertEquals(Mav.STATE_CRITICAL, payload[7].toInt() and 0xFF)
    }
}
