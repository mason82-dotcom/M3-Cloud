package com.lyrebird.rc.controller

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ThermalMediaNamingTest {

    @Test
    fun integratedThermalPlatformsAcceptTAndRSuffixes() {
        listOf(CameraPlatform.M3T, CameraPlatform.M4T).forEach { platform ->
            assertTrue(ThermalMediaNaming.isThermalFile(platform, "DJI_0001_T.JPG"))
            assertTrue(ThermalMediaNaming.isThermalFile(platform, "DJI_0001_R.JPG"))
            assertEquals(
                "DJI_0001",
                ThermalMediaNaming.captureGroupBase(platform, "DJI_0001_R.JPG")
            )
        }
    }

    @Test
    fun m3mRedBandCannotBecomeThermal() {
        assertFalse(
            ThermalMediaNaming.isThermalFile(
                CameraPlatform.M3M,
                "DJI_0001_MS_R.TIF"
            )
        )
        assertEquals(
            "DJI_0001_MS_R",
            ThermalMediaNaming.captureGroupBase(
                CameraPlatform.M3M,
                "DJI_0001_MS_R.TIF"
            )
        )
    }

    @Test
    fun legacyHybridStillRequiresExplicitTSuffix() {
        assertTrue(
            ThermalMediaNaming.isThermalFile(
                CameraPlatform.LEGACY_HYBRID,
                "DJI_0001_T.JPG"
            )
        )
        assertFalse(
            ThermalMediaNaming.isThermalFile(
                CameraPlatform.LEGACY_HYBRID,
                "DJI_0001_R.JPG"
            )
        )
    }
}
