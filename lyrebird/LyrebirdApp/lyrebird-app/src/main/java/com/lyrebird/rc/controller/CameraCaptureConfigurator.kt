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

/**
 * Product-specific still-capture profiles for the Mavic 3 family.
 *
 * The lists are deliberately explicit: an M3M multispectral exposure is not an M3E wide exposure
 * with extra files bolted on, and M3T thermal capture must never be enabled on M3E/M3M.
 */
internal enum class CameraCaptureProfile(
    val platform: CameraPlatform,
    val storedSources: List<CameraVideoStreamSourceType>
) {
    M3E_MAPPING(
        CameraPlatform.M3E,
        listOf(CameraVideoStreamSourceType.WIDE_CAMERA)
    ),
    M3T_WIDE(
        CameraPlatform.M3T,
        listOf(CameraVideoStreamSourceType.WIDE_CAMERA)
    ),
    M3T_THERMAL(
        CameraPlatform.M3T,
        listOf(CameraVideoStreamSourceType.INFRARED_CAMERA)
    ),
    M3M_RGB(
        CameraPlatform.M3M,
        listOf(CameraVideoStreamSourceType.RGB_CAMERA)
    ),
    M3M_RGB_MULTISPECTRAL(
        CameraPlatform.M3M,
        listOf(
            CameraVideoStreamSourceType.RGB_CAMERA,
            CameraVideoStreamSourceType.NDVI_CAMERA,
            CameraVideoStreamSourceType.MS_G_CAMERA,
            CameraVideoStreamSourceType.MS_R_CAMERA,
            CameraVideoStreamSourceType.MS_RE_CAMERA,
            CameraVideoStreamSourceType.MS_NIR_CAMERA
        )
    );

    val storedSourceNames: Set<String>
        get() = storedSources.mapTo(linkedSetOf()) { it.name }
}

internal data class CameraPrepareResult(
    val success: Boolean,
    val profile: CameraCaptureProfile?,
    val detail: String
)

internal object CameraCaptureConfigurator {

    fun defaultDirectProfile(capabilities: CameraPlatformCapabilities): CameraCaptureProfile? =
        when (capabilities.platform) {
            CameraPlatform.M3E -> CameraCaptureProfile.M3E_MAPPING
            CameraPlatform.M3T -> CameraCaptureProfile.M3T_WIDE
            CameraPlatform.M3M -> CameraCaptureProfile.M3M_RGB
            else -> null
        }

    fun defaultSurveyProfile(capabilities: CameraPlatformCapabilities): CameraCaptureProfile? =
        when (capabilities.platform) {
            CameraPlatform.M3E -> CameraCaptureProfile.M3E_MAPPING
            CameraPlatform.M3T -> CameraCaptureProfile.M3T_WIDE
            CameraPlatform.M3M -> CameraCaptureProfile.M3M_RGB_MULTISPECTRAL
            else -> null
        }

    fun thermalProfile(capabilities: CameraPlatformCapabilities): CameraCaptureProfile? =
        if (capabilities.platform == CameraPlatform.M3T && capabilities.supportsThermalCapture) {
            CameraCaptureProfile.M3T_THERMAL
        } else {
            null
        }

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
        val missing = profile.storedSources.filterNot { it in supportedSources }
        if (missing.isNotEmpty()) {
            callback(
                CameraPrepareResult(
                    false,
                    profile,
                    "Camera does not report capture source(s): ${missing.joinToString { it.name }}"
                )
            )
            return
        }

        val modeKey: DJIKey<CameraMode> = KeyTools.createKey(CameraKey.KeyCameraMode, index)
        val captureKey: DJIKey<CameraStreamSettingsInfo> =
            KeyTools.createKey(CameraKey.KeyCaptureCameraStreamSettings, index)

        modeKey.set(
            CameraMode.PHOTO_NORMAL,
            onSuccess = {
                val settings = CameraStreamSettingsInfo()
                    .setRequestCurrentScreen(false)
                    .setCameraVideoStreamSources(ArrayList(profile.storedSources))
                captureKey.set(
                    settings,
                    onSuccess = {
                        val readback = captureKey.get(CameraStreamSettingsInfo())
                            ?.cameraVideoStreamSources
                            .orEmpty()
                        val expected = profile.storedSources.map { it.name }.toSet()
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
