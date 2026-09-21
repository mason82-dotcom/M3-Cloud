package com.lyrebird.rc.controller

/**
 * Product-level camera capabilities Lyrebird can assert without guessing from filenames.
 *
 * Keep integrated enterprise-camera platforms separate. M3T and M4T are both thermal-capable,
 * but they are not interchangeable: M4T adds a different visual camera stack and RC Plus 2
 * deployment target, while M3M owns multispectral storage.
 */
internal enum class CameraPlatform {
    M3E,
    M3T,
    M3M,
    M4T,
    LEGACY_HYBRID,
    OTHER
}

internal data class CameraPlatformCapabilities(
    val platform: CameraPlatform,
    val supportsThermalCapture: Boolean,
    val supportsMultispectralCapture: Boolean,
    val supportsM3mRgbOnlyProfile: Boolean,
    val supportsM3mRgbMultispectralProfile: Boolean
) {
    val isM3Family: Boolean
        get() = platform == CameraPlatform.M3E ||
            platform == CameraPlatform.M3T ||
            platform == CameraPlatform.M3M

    val isIntegratedThermalPlatform: Boolean
        get() = platform == CameraPlatform.M3T || platform == CameraPlatform.M4T

    companion object {
        /**
         * Accept the SDK enum name rather than the enum itself so this policy remains JVM-testable
         * and unknown/new MSDK camera types fail closed instead of accidentally inheriting another
         * platform's capabilities.
         */
        fun fromCameraTypeName(rawName: String?): CameraPlatformCapabilities {
            val name = rawName.orEmpty().uppercase()
            return when (name) {
                "M3E" -> CameraPlatformCapabilities(
                    platform = CameraPlatform.M3E,
                    supportsThermalCapture = false,
                    supportsMultispectralCapture = false,
                    supportsM3mRgbOnlyProfile = false,
                    supportsM3mRgbMultispectralProfile = false
                )
                "M3T", "M3TA" -> CameraPlatformCapabilities(
                    platform = CameraPlatform.M3T,
                    supportsThermalCapture = true,
                    supportsMultispectralCapture = false,
                    supportsM3mRgbOnlyProfile = false,
                    supportsM3mRgbMultispectralProfile = false
                )
                "M3M" -> CameraPlatformCapabilities(
                    platform = CameraPlatform.M3M,
                    supportsThermalCapture = false,
                    supportsMultispectralCapture = true,
                    supportsM3mRgbOnlyProfile = true,
                    supportsM3mRgbMultispectralProfile = true
                )
                "M4T" -> CameraPlatformCapabilities(
                    platform = CameraPlatform.M4T,
                    supportsThermalCapture = true,
                    supportsMultispectralCapture = false,
                    supportsM3mRgbOnlyProfile = false,
                    supportsM3mRgbMultispectralProfile = false
                )
                "ZENMUSE_H20T", "ZENMUSE_H20N", "ZENMUSE_H30T" ->
                    CameraPlatformCapabilities(
                        platform = CameraPlatform.LEGACY_HYBRID,
                        supportsThermalCapture = true,
                        supportsMultispectralCapture = false,
                        supportsM3mRgbOnlyProfile = false,
                        supportsM3mRgbMultispectralProfile = false
                    )
                else -> CameraPlatformCapabilities(
                    platform = CameraPlatform.OTHER,
                    supportsThermalCapture = false,
                    supportsMultispectralCapture = false,
                    supportsM3mRgbOnlyProfile = false,
                    supportsM3mRgbMultispectralProfile = false
                )
            }
        }
    }
}
