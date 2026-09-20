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
import dji.v5.et.set

internal data class CameraPrepareResult(
    val success: Boolean,
    val profile: CameraCaptureProfile?,
    val detail: String
)

internal object CameraCaptureConfigurator {

    fun defaultDirectProfile(capabilities: CameraPlatformCapabilities): CameraCaptureProfile? =
        CameraCapturePolicy.defaultDirectProfile(capabilities)

    fun defaultSurveyProfile(capabilities: CameraPlatformCapabilities): CameraCaptureProfile? =
        CameraCapturePolicy.defaultSurveyProfile(capabilities)

    fun thermalProfile(capabilities: CameraPlatformCapabilities): CameraCaptureProfile? =
        CameraCapturePolicy.thermalProfile(capabilities)

    /**
     * Prepare PHOTO_NORMAL and its stored lens sources, then verify the capture-source readback.
     *
     * This method is asynchronous on purpose. MSDK action/key callbacks must not be turned into a
     * main-thread blocking wait. Callers that already run a worker can wait on their own latch.
     */
    fun preparePhoto(
        profile: CameraCaptureProfile,
        index: ComponentIndexType = ComponentIndexType.LEFT_OR_MAIN,
        callback: (CameraPrepareResult) -> Unit
    ) {
        val typeKey: DJIKey<CameraType> = KeyTools.createKey(CameraKey.KeyCameraType, index)
        val cameraType = typeKey.get(CameraType.NOT_SUPPORTED)
        val capabilities =
            CameraPlatformCapabilities.fromCameraTypeName(cameraType?.name)

        if (capabilities.platform != profile.platform) {
            callback(
                CameraPrepareResult(
                    false,
                    profile,
                    "Profile ${profile.name} does not match camera ${cameraType?.name ?: "UNKNOWN"}"
                )
            )
            return
        }

        val sourceRangeKey: DJIKey<List<CameraVideoStreamSourceType>> =
            KeyTools.createKey(CameraKey.KeyCameraVideoStreamSourceRange, index)
        val supportedSources = sourceRangeKey.get(emptyList())
        val supportedByName = supportedSources.associateBy { it.name }
        val missing = profile.storedSourceNames.filterNot(supportedByName::containsKey)
        if (missing.isNotEmpty()) {
            callback(
                CameraPrepareResult(
                    false,
                    profile,
                    "Camera does not report capture source(s): ${missing.joinToString()}"
                )
            )
            return
        }
        val requestedSources = profile.storedSourceNames.mapNotNull(supportedByName::get)

        val modeKey: DJIKey<CameraMode> = KeyTools.createKey(CameraKey.KeyCameraMode, index)
        val captureKey: DJIKey<CameraStreamSettingsInfo> =
            KeyTools.createKey(CameraKey.KeyCaptureCameraStreamSettings, index)

        modeKey.set(
            CameraMode.PHOTO_NORMAL,
            onSuccess = {
                val settings = CameraStreamSettingsInfo()
                    .setRequestCurrentScreen(false)
                    .setCameraVideoStreamSources(ArrayList(requestedSources))
                captureKey.set(
                    settings,
                    onSuccess = {
                        val readback = captureKey.get(CameraStreamSettingsInfo())
                            ?.cameraVideoStreamSources
                            .orEmpty()
                        val expected = profile.storedSourceNames.toSet()
                        val actual = readback.map { it.name }.toSet()
                        if (actual == expected) {
                            callback(
                                CameraPrepareResult(
                                    true,
                                    profile,
                                    "PHOTO_NORMAL; sources=${expected.sorted()}"
                                )
                            )
                        } else {
                            callback(
                                CameraPrepareResult(
                                    false,
                                    profile,
                                    "Capture source readback mismatch: expected=$expected actual=$actual"
                                )
                            )
                        }
                    },
                    onFailure = { error ->
                        callback(
                            CameraPrepareResult(
                                false,
                                profile,
                                "Capture-stream setting failed: ${error.description()}"
                            )
                        )
                    }
                )
            },
            onFailure = { error ->
                callback(
                    CameraPrepareResult(
                        false,
                        profile,
                        "PHOTO_NORMAL failed: ${error.description()}"
                    )
                )
            }
        )
    }
}
