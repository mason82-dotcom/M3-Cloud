package com.lyrebird.rc.controller

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CameraPlatformCapabilitiesTest {

    @Test
    fun m3eDoesNotInheritThermalOrMultispectralCapabilities() {
        val caps = CameraPlatformCapabilities.fromCameraTypeName("M3E")
        assertEquals(CameraPlatform.M3E, caps.platform)
        assertFalse(caps.supportsThermalCapture)
        assertFalse(caps.supportsMultispectralCapture)
    }

    @Test
    fun m3tOwnsThermalCapabilityOnly() {
        val caps = CameraPlatformCapabilities.fromCameraTypeName("M3T")
        assertEquals(CameraPlatform.M3T, caps.platform)
        assertTrue(caps.supportsThermalCapture)
        assertFalse(caps.supportsMultispectralCapture)
    }

    @Test
    fun m3mOwnsOnlyTheTwoSupportedMultispectralProfileFamilies() {
        val caps = CameraPlatformCapabilities.fromCameraTypeName("M3M")
        assertEquals(CameraPlatform.M3M, caps.platform)
        assertFalse(caps.supportsThermalCapture)
        assertTrue(caps.supportsMultispectralCapture)
        assertTrue(caps.supportsM3mRgbOnlyProfile)
        assertTrue(caps.supportsM3mRgbMultispectralProfile)
    }

    @Test
    fun legacyHybridPayloadsRetainThermalCapability() {
        listOf("ZENMUSE_H20T", "ZENMUSE_H20N", "ZENMUSE_H30T").forEach { name ->
            val caps = CameraPlatformCapabilities.fromCameraTypeName(name)
            assertEquals(CameraPlatform.LEGACY_HYBRID, caps.platform)
            assertTrue(caps.supportsThermalCapture)
            assertFalse(caps.supportsMultispectralCapture)
        }
    }

    @Test
    fun unknownCameraFailsClosed() {
        val caps = CameraPlatformCapabilities.fromCameraTypeName("FUTURE_CAMERA")
        assertEquals(CameraPlatform.OTHER, caps.platform)
        assertFalse(caps.supportsThermalCapture)
        assertFalse(caps.supportsMultispectralCapture)
    }
}
