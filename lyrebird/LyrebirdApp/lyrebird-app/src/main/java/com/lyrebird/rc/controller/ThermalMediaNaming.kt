package com.lyrebird.rc.controller

/**
 * Filename grouping policy for radiometric/visual files produced by DJI thermal cameras.
 *
 * Integrated M3T/M4T cameras may expose radiometric JPEGs with _T or _R suffixes.
 * Legacy H20/H30 hybrid payloads keep the established _T thermal suffix. M3M is
 * deliberately excluded from _R thermal handling because _MS_R.TIF is its red band.
 */
internal object ThermalMediaNaming {
    private val integratedThermalSuffix = Regex("_[TRWVZ]$")
    private val standardLensSuffix = Regex("_[TWVZ]$")

    private fun baseNameNoExt(name: String?): String =
        (name ?: "").substringBeforeLast('.').uppercase()

    fun isThermalFile(platform: CameraPlatform, name: String?): Boolean {
        val base = baseNameNoExt(name)
        return when (platform) {
            CameraPlatform.M3T,
            CameraPlatform.M4T -> base.endsWith("_T") || base.endsWith("_R")
            CameraPlatform.LEGACY_HYBRID -> base.endsWith("_T")
            else -> false
        }
    }

    fun captureGroupBase(platform: CameraPlatform, name: String?): String {
        val base = baseNameNoExt(name)
        val suffix = when (platform) {
            CameraPlatform.M3T,
            CameraPlatform.M4T -> integratedThermalSuffix
            else -> standardLensSuffix
        }
        return suffix.replace(base, "")
    }
}
