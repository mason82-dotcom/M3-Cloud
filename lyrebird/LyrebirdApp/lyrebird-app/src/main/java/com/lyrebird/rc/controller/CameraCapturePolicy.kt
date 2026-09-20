package com.lyrebird.rc.controller

/**
 * SDK-free capture policy for Mavic 3 Enterprise-family payloads.
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
    )
}

internal object CameraCapturePolicy {
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
}
