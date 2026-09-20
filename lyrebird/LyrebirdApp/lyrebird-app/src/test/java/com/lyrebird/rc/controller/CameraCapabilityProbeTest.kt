package com.lyrebird.rc.controller

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CameraCapabilityProbeTest {

    @Test
    fun jsonKeepsPlatformAndRuntimeSourcesSeparate() {
        val json = JSONObject(
            CameraCapabilitySnapshot(
                componentIndex = "LEFT_OR_MAIN",
                connected = true,
                cameraType = "M3M",
                firmwareVersion = "17.01.05.08",
                platform = "M3M",
                cameraMode = "PHOTO_NORMAL",
                cameraModeRange = listOf("PHOTO_NORMAL", "VIDEO_NORMAL"),
                liveViewSource = "RGB_CAMERA",
                liveViewSourceRange = listOf(
                    "RGB_CAMERA", "NDVI_CAMERA", "MS_G_CAMERA", "MS_R_CAMERA",
                    "MS_RE_CAMERA", "MS_NIR_CAMERA"
                ),
                captureStoredSources = listOf(
                    "RGB_CAMERA", "NDVI_CAMERA", "MS_G_CAMERA", "MS_R_CAMERA",
                    "MS_RE_CAMERA", "MS_NIR_CAMERA"
                ),
                recordStoredSources = listOf("RGB_CAMERA", "NDVI_CAMERA"),
                captureStorageReadStatus = "OK",
                recordStorageReadStatus = "NOT_APPLICABLE",
                captureCurrentScreen = false,
                thermalCapture = false,
                multispectralCapture = true
            ).toJson()
        )

        assertEquals("M3M", json.getString("cameraType"))
        assertEquals("M3M", json.getString("platform"))
        assertFalse(json.getBoolean("thermalCapture"))
        assertTrue(json.getBoolean("multispectralCapture"))
        assertEquals(6, json.getJSONArray("captureStoredSources").length())
        assertEquals(2, json.getJSONArray("recordStoredSources").length())
        assertEquals("NDVI_CAMERA", json.getJSONArray("recordStoredSources").getString(1))
        assertEquals("OK", json.getString("captureStorageReadStatus"))
        assertEquals("NOT_APPLICABLE", json.getString("recordStorageReadStatus"))
    }
}
