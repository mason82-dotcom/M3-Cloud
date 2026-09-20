package com.lyrebird.rc.controller

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class CameraCaptureConfiguratorTest {

    @Test
    fun directProfilesStayPlatformSpecific() {
        assertEquals(
            CameraCaptureProfile.M3E_MAPPING,
            CameraCaptureConfigurator.defaultDirectProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M3E")
            )
        )
        assertEquals(
            CameraCaptureProfile.M3T_WIDE,
            CameraCaptureConfigurator.defaultDirectProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M3T")
            )
        )
        assertEquals(
            CameraCaptureProfile.M3M_RGB,
            CameraCaptureConfigurator.defaultDirectProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M3M")
            )
        )
    }

    @Test
    fun m3mSurveyUsesRgbAndAllDocumentedMultispectralSources() {
        val profile = CameraCaptureConfigurator.defaultSurveyProfile(
            CameraPlatformCapabilities.fromCameraTypeName("M3M")
        )!!
        assertEquals(CameraCaptureProfile.M3M_RGB_MULTISPECTRAL, profile)
        assertEquals(
            setOf("RGB_CAMERA", "NDVI_CAMERA", "MS_G_CAMERA", "MS_R_CAMERA", "MS_RE_CAMERA", "MS_NIR_CAMERA"),
            profile.storedSourceNames
        )
    }

    @Test
    fun thermalProfileExistsOnlyForM3t() {
        assertEquals(
            CameraCaptureProfile.M3T_THERMAL,
            CameraCaptureConfigurator.thermalProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M3T")
            )
        )
        assertNull(
            CameraCaptureConfigurator.thermalProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M3E")
            )
        )
        assertNull(
            CameraCaptureConfigurator.thermalProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M3M")
            )
        )
    }
}
