package com.lyrebird.rc.controller

/**
 * Selects the MSDK camera-lens address used for focal/zoom keys without collapsing M3E, M3T
 * and M3M into one Enterprise-series bucket.
 */
internal enum class CameraFocalLensRole {
    RGB,
    ZOOM,
    DEFAULT
}

internal object CameraFocalLensPolicy {
    fun fromCameraTypeName(rawName: String?): CameraFocalLensRole =
        when (rawName.orEmpty().uppercase()) {
            "M3M" -> CameraFocalLensRole.RGB
            "M3E", "M3T", "M3TA" -> CameraFocalLensRole.ZOOM
            else -> CameraFocalLensRole.DEFAULT
        }
}
