package com.lyrebird.rc.mavlink

import kotlin.math.roundToInt

internal data class SurveyDistanceCapture(
    val startWaypointIndex: Int,
    val endWaypointIndex: Int,
    val distanceM: Double,
    val triggerImmediately: Boolean,
    val targetCameraId: Int
)

internal object SurveyDistanceCompiler {

    fun compile(items: List<MissionItem>): List<SurveyDistanceCapture> {
        val lastWaypointIndex = items.count { it.isWaypoint } - 1
        if (lastWaypointIndex < 0) return emptyList()

        data class Active(
            val startWaypointIndex: Int,
            val distanceM: Double,
            val triggerImmediately: Boolean,
            val targetCameraId: Int
        )

        val result = mutableListOf<SurveyDistanceCapture>()
        var active: Active? = null
        var waypointIndex = -1

        fun closeActive(endWaypointIndex: Int) {
            val current = active ?: return
            result += SurveyDistanceCapture(
                startWaypointIndex = current.startWaypointIndex,
                endWaypointIndex = endWaypointIndex.coerceAtLeast(current.startWaypointIndex),
                distanceM = current.distanceM,
                triggerImmediately = current.triggerImmediately,
                targetCameraId = current.targetCameraId
            )
            active = null
        }

        for (item in items) {
            if (item.isWaypoint) {
                waypointIndex += 1
                continue
            }
            if (item.command != Mav.CMD_DO_SET_CAM_TRIGG_DIST) continue

            val distanceM = item.param1.toDouble()
            require(distanceM.isFinite() && distanceM >= 0.0) {
                "Camera trigger distance must be finite and >= 0 m"
            }

            val triggerRaw = item.param3.toDouble()
            require(!triggerRaw.isFinite() || triggerRaw == 0.0 || triggerRaw == 1.0) {
                "Camera trigger param3 must be MAV_BOOL (0 or 1)"
            }
            val triggerImmediately = triggerRaw == 1.0

            val targetCameraId = if (item.param4.isFinite()) item.param4.roundToInt() else 0
            require(targetCameraId in 0..255) {
                "Camera target id must be in 0..255"
            }

            if (distanceM == 0.0) {
                closeActive(waypointIndex.coerceAtLeast(0))
                continue
            }

            closeActive(waypointIndex.coerceAtLeast(0))
            active = Active(
                startWaypointIndex = waypointIndex.coerceAtLeast(0),
                distanceM = distanceM,
                triggerImmediately = triggerImmediately,
                targetCameraId = targetCameraId
            )
        }

        if (active != null) closeActive(lastWaypointIndex)
        return result
    }
}
