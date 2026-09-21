package com.lyrebird.rc.controller

import org.junit.Assert.assertEquals
import org.junit.Test

class CameraLiveSourceControllerTest {

    @Test
    fun failedRangeReadIsNotReady() {
        assertEquals(
            CameraLiveSourceAvailability.NOT_READY,
            classifyCameraLiveSourceAvailability(
                requested = "NDVI_CAMERA",
                rangeReadSucceeded = false,
                supportedSourceNames = listOf("RGB_CAMERA", "NDVI_CAMERA")
            )
        )
    }

    @Test
    fun emptyRangeIsNotReadyEvenWhenReadCompleted() {
        assertEquals(
            CameraLiveSourceAvailability.NOT_READY,
            classifyCameraLiveSourceAvailability(
                requested = "NDVI_CAMERA",
                rangeReadSucceeded = true,
                supportedSourceNames = emptyList()
            )
        )
    }

    @Test
    fun missingRequestedSourceIsReportedUnavailable() {
        assertEquals(
            CameraLiveSourceAvailability.SOURCE_NOT_AVAILABLE,
            classifyCameraLiveSourceAvailability(
                requested = "NDVI_CAMERA",
                rangeReadSucceeded = true,
                supportedSourceNames = listOf("RGB_CAMERA")
            )
        )
    }

    @Test
    fun m3mNdviIsReadyWhenRuntimeRangeContainsIt() {
        assertEquals(
            CameraLiveSourceAvailability.READY,
            classifyCameraLiveSourceAvailability(
                requested = "NDVI_CAMERA",
                rangeReadSucceeded = true,
                supportedSourceNames = listOf(
                    "RGB_CAMERA",
                    "NDVI_CAMERA",
                    "MS_G_CAMERA",
                    "MS_R_CAMERA",
                    "MS_RE_CAMERA",
                    "MS_NIR_CAMERA"
                )
            )
        )
    }
}
