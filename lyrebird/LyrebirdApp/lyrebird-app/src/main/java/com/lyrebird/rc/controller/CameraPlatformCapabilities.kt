package com.lyrebird.rc.controller

/**
 * Product-level camera capabilities Lyrebird can assert without guessing from filenames.
 *
 * This layer deliberately keeps the M3E, M3T and M3M separate. A shared "Mavic 3 Enterprise"
 * bucket is not sufficient for capture configuration: M3T has thermal, M3M has multispectral
 * storage, and M3E has neither.
 */
internal enum class CameraPlatform {
    M3E,
    M3T,
    M3M,
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
