package com.lyrebird.rc.mavlink

internal data class SurveyDistanceCapture(
    val startWaypointIndex: Int,
    val endWaypointIndex: Int,
    val distanceM: Double,
    /** Preserved for trace/debugging only. Lyrebird assigns no portable control meaning to it. */
    val param3Raw: Double?,
    /** Preserved for trace/debugging only. It is not treated as a DJI payload/camera id. */
    val param4Raw: Double?
)

internal object SurveyDistanceCompiler {

    fun compile(items: List<MissionItem>): List<SurveyDistanceCapture> {
        val lastWaypointIndex = items.count { it.isWaypoint } - 1
        if (lastWaypointIndex < 0) return emptyList()

        data class Active(
            val startWaypointIndex: Int,
            val distanceM: Double,
            val param3Raw: Double?,
            val param4Raw: Double?
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
                param3Raw = current.param3Raw,
                param4Raw = current.param4Raw
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

            if (distanceM == 0.0) {
                closeActive(waypointIndex.coerceAtLeast(0))
                continue
            }

            closeActive(waypointIndex.coerceAtLeast(0))
            active = Active(
                startWaypointIndex = waypointIndex.coerceAtLeast(0),
                distanceM = distanceM,
                param3Raw = item.param3.toDouble().takeIf { it.isFinite() },
                param4Raw = item.param4.toDouble().takeIf { it.isFinite() }
            )
        }

        if (active != null) closeActive(lastWaypointIndex)
        return result
    }
}
