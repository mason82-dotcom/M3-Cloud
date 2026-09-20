package com.lyrebird.rc.controller

import dji.sdk.keyvalue.key.CameraKey
import dji.sdk.keyvalue.key.DJIKey
import dji.sdk.keyvalue.key.KeyTools
import dji.sdk.keyvalue.value.camera.CameraMode
import dji.sdk.keyvalue.value.camera.CameraStreamSettingsInfo
import dji.sdk.keyvalue.value.camera.CameraType
import dji.sdk.keyvalue.value.camera.CameraVideoStreamSourceType
import dji.sdk.keyvalue.value.common.ComponentIndexType
import dji.v5.et.get
import org.json.JSONArray
import org.json.JSONObject

/**
 * Read-only MSDK 5.18 camera characterization.
 *
 * This probe never changes camera mode, live-view source or capture storage. Its purpose is to
 * expose the exact values the attached aircraft reports before Lyrebird chooses a product-specific
 * capture profile. That is especially important for keeping M3E, M3T and M3M behavior separate.
 */
internal object CameraCapabilityProbe {

    private fun <T> key(
        info: dji.sdk.keyvalue.key.DJIKeyInfo<T>,
        index: ComponentIndexType
    ): DJIKey<T> = KeyTools.createKey(info, index)

    fun snapshot(
        index: ComponentIndexType = ComponentIndexType.LEFT_OR_MAIN
    ): CameraCapabilitySnapshot {
        val type = key(CameraKey.KeyCameraType, index).get(CameraType.NOT_SUPPORTED)
        val typeName = type?.name ?: "NOT_SUPPORTED"
        val platformCaps = CameraPlatformCapabilities.fromCameraTypeName(typeName)

        val mode = key(CameraKey.KeyCameraMode, index).get(CameraMode.UNKNOWN)
        val modeRange = key(CameraKey.KeyCameraModeRange, index).get(emptyList())
        val liveSource = key(CameraKey.KeyCameraVideoStreamSource, index)
            .get(CameraVideoStreamSourceType.DEFAULT_CAMERA)
        val liveSourceRange = key(CameraKey.KeyCameraVideoStreamSourceRange, index).get(emptyList())
        val captureSettings = key(CameraKey.KeyCaptureCameraStreamSettings, index)
            .get(CameraStreamSettingsInfo())
        val recordSettings = key(CameraKey.KeyRecordCameraStreamSettings, index)
            .get(CameraStreamSettingsInfo())
        val firmware = key(CameraKey.KeyFirmwareVersion, index).get("")
        val connected = key(CameraKey.KeyConnection, index).get(false)

        return CameraCapabilitySnapshot(
            componentIndex = index.name,
            connected = connected,
            cameraType = typeName,
            firmwareVersion = firmware.orEmpty(),
            platform = platformCaps.platform.name,
            cameraMode = mode?.name ?: "UNKNOWN",
            cameraModeRange = modeRange.map { it.name },
            liveViewSource = liveSource?.name ?: "UNKNOWN",
            liveViewSourceRange = liveSourceRange.map { it.name },
            captureStoredSources = captureSettings?.cameraVideoStreamSources
                ?.map { it.name }
                .orEmpty(),
            recordStoredSources = recordSettings?.cameraVideoStreamSources
                ?.map { it.name }
                .orEmpty(),
            captureCurrentScreen = captureSettings?.requestCurrentScreen ?: false,
            thermalCapture = platformCaps.supportsThermalCapture,
            multispectralCapture = platformCaps.supportsMultispectralCapture
        )
    }
}

internal data class CameraCapabilitySnapshot(
    val componentIndex: String,
    val connected: Boolean,
    val cameraType: String,
    val firmwareVersion: String,
    val platform: String,
    val cameraMode: String,
    val cameraModeRange: List<String>,
    val liveViewSource: String,
    val liveViewSourceRange: List<String>,
    val captureStoredSources: List<String>,
    val recordStoredSources: List<String>,
    val captureCurrentScreen: Boolean,
    val thermalCapture: Boolean,
    val multispectralCapture: Boolean
) {
    fun toJson(): String = JSONObject()
        .put("componentIndex", componentIndex)
        .put("connected", connected)
        .put("cameraType", cameraType)
        .put("firmwareVersion", firmwareVersion)
        .put("platform", platform)
        .put("cameraMode", cameraMode)
        .put("cameraModeRange", JSONArray(cameraModeRange))
        .put("liveViewSource", liveViewSource)
        .put("liveViewSourceRange", JSONArray(liveViewSourceRange))
        .put("captureStoredSources", JSONArray(captureStoredSources))
        .put("recordStoredSources", JSONArray(recordStoredSources))
        .put("captureCurrentScreen", captureCurrentScreen)
        .put("thermalCapture", thermalCapture)
        .put("multispectralCapture", multispectralCapture)
        .toString()
}
