package com.lyrebird.rc.controller

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class CameraCaptureConfiguratorTest {

    @Test
    fun directProfilesStayPlatformSpecific() {
        assertEquals(
            CameraCaptureProfile.M3E_MAPPING,
            CameraCapturePolicy.defaultDirectProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M3E")
            )
        )
        assertEquals(
            CameraCaptureProfile.M3T_WIDE,
            CameraCapturePolicy.defaultDirectProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M3T")
            )
        )
        assertEquals(
            CameraCaptureProfile.M3M_RGB,
            CameraCapturePolicy.defaultDirectProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M3M")
            )
        )
        assertEquals(
            CameraCaptureProfile.M4T_WIDE,
            CameraCapturePolicy.defaultDirectProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M4T")
            )
        )
    }

    @Test
    fun m3mSurveyUsesRgbAndAllDocumentedMultispectralSources() {
        val profile = CameraCapturePolicy.defaultSurveyProfile(
            CameraPlatformCapabilities.fromCameraTypeName("M3M")
        )!!
        assertEquals(CameraCaptureProfile.M3M_RGB_MULTISPECTRAL, profile)
        assertEquals(
            listOf("RGB_CAMERA", "NDVI_CAMERA", "MS_G_CAMERA", "MS_R_CAMERA", "MS_RE_CAMERA", "MS_NIR_CAMERA"),
            profile.storedSourceNames
        )
    }

    @Test
    fun m4tSurveyDefaultsToWideStorageUntilPairedCaptureIsFieldValidated() {
        val profile = CameraCapturePolicy.defaultSurveyProfile(
            CameraPlatformCapabilities.fromCameraTypeName("M4T")
        )
        assertEquals(CameraCaptureProfile.M4T_WIDE, profile)
    }

    @Test
    fun thermalProfilesArePlatformSpecific() {
        assertEquals(
            CameraCaptureProfile.M3T_THERMAL,
            CameraCapturePolicy.thermalProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M3T")
            )
        )
        assertEquals(
            CameraCaptureProfile.M4T_THERMAL,
            CameraCapturePolicy.thermalProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M4T")
            )
        )
        assertNull(
            CameraCapturePolicy.thermalProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M3E")
            )
        )
        assertNull(
            CameraCapturePolicy.thermalProfile(
                CameraPlatformCapabilities.fromCameraTypeName("M3M")
            )
        )
    }
}
