package com.lyrebird.rc.controller

/**
 * SDK-free capture policy for DJI integrated enterprise camera platforms.
 *
 * Keep product identity and requested stored sources as plain names so policy/unit tests never
 * need to load DJI Android classes. The MSDK adapter resolves these names against the runtime
 * source range immediately before applying camera settings.
 */
internal enum class CameraCaptureProfile(
    val platform: CameraPlatform,
    val storedSourceNames: List<String>
) {
    M3E_MAPPING(
        CameraPlatform.M3E,
        listOf("WIDE_CAMERA")
    ),
    M3T_WIDE(
        CameraPlatform.M3T,
        listOf("WIDE_CAMERA")
    ),
    M3T_THERMAL(
        CameraPlatform.M3T,
        listOf("INFRARED_CAMERA")
    ),
    M3M_RGB(
        CameraPlatform.M3M,
        listOf("RGB_CAMERA")
    ),
    M3M_RGB_MULTISPECTRAL(
        CameraPlatform.M3M,
        listOf(
            "RGB_CAMERA",
            "NDVI_CAMERA",
            "MS_G_CAMERA",
            "MS_R_CAMERA",
            "MS_RE_CAMERA",
            "MS_NIR_CAMERA"
        )
    ),
    M4T_WIDE(
        CameraPlatform.M4T,
        listOf("WIDE_CAMERA")
    ),
    M4T_THERMAL(
        CameraPlatform.M4T,
        listOf("INFRARED_CAMERA")
    )
}

internal object CameraCapturePolicy {
    fun defaultDirectProfile(capabilities: CameraPlatformCapabilities): CameraCaptureProfile? =
        when (capabilities.platform) {
            CameraPlatform.M3E -> CameraCaptureProfile.M3E_MAPPING
            CameraPlatform.M3T -> CameraCaptureProfile.M3T_WIDE
            CameraPlatform.M3M -> CameraCaptureProfile.M3M_RGB
            CameraPlatform.M4T -> CameraCaptureProfile.M4T_WIDE
            else -> null
        }

    fun defaultSurveyProfile(capabilities: CameraPlatformCapabilities): CameraCaptureProfile? =
        when (capabilities.platform) {
            CameraPlatform.M3E -> CameraCaptureProfile.M3E_MAPPING
            CameraPlatform.M3T -> CameraCaptureProfile.M3T_WIDE
            CameraPlatform.M3M -> CameraCaptureProfile.M3M_RGB_MULTISPECTRAL
            CameraPlatform.M4T -> CameraCaptureProfile.M4T_WIDE
            else -> null
        }

    fun thermalProfile(capabilities: CameraPlatformCapabilities): CameraCaptureProfile? =
        when {
            !capabilities.supportsThermalCapture -> null
            capabilities.platform == CameraPlatform.M3T -> CameraCaptureProfile.M3T_THERMAL
            capabilities.platform == CameraPlatform.M4T -> CameraCaptureProfile.M4T_THERMAL
            else -> null
        }
}
