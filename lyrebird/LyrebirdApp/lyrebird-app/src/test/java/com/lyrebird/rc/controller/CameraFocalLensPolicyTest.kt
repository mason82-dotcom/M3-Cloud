package com.lyrebird.rc.controller

import org.junit.Assert.assertEquals
import org.junit.Test

class CameraFocalLensPolicyTest {

    @Test
    fun m3mUsesRgbLensForFocalKeys() {
        assertEquals(
            CameraFocalLensRole.RGB,
            CameraFocalLensPolicy.fromCameraTypeName("M3M")
        )
    }

    @Test
    fun m3eAndM3tUseZoomLensForFocalKeys() {
        assertEquals(CameraFocalLensRole.ZOOM, CameraFocalLensPolicy.fromCameraTypeName("M3E"))
        assertEquals(CameraFocalLensRole.ZOOM, CameraFocalLensPolicy.fromCameraTypeName("M3T"))
        assertEquals(CameraFocalLensRole.ZOOM, CameraFocalLensPolicy.fromCameraTypeName("M3TA"))
    }

    @Test
    fun unknownCameraFailsClosedToDefaultLens() {
        assertEquals(
            CameraFocalLensRole.DEFAULT,
            CameraFocalLensPolicy.fromCameraTypeName("FUTURE_CAMERA")
        )
    }
}
