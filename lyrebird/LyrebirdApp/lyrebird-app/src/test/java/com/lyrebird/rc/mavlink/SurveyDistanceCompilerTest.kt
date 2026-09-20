package com.lyrebird.rc.mavlink

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SurveyDistanceCompilerTest {

    private fun waypoint(seq: Int) = MissionItem(
        seq = seq,
        command = Mav.CMD_NAV_WAYPOINT,
        param1 = 0f,
        param2 = 0f,
        param3 = 0f,
        param4 = Float.NaN,
        latitudeDeg = 49.0 + seq * 0.001,
        longitudeDeg = 8.0,
        altitudeM = 70.0,
        autocontinue = true
    )

    private fun distance(
        seq: Int,
        metres: Float,
        triggerNow: Float = 0f,
        cameraId: Float = 0f
    ) = MissionItem(
        seq = seq,
        command = Mav.CMD_DO_SET_CAM_TRIGG_DIST,
        param1 = metres,
        param2 = 0f,
        param3 = triggerNow,
        param4 = cameraId,
        latitudeDeg = 0.0,
        longitudeDeg = 0.0,
        altitudeM = 0.0,
        autocontinue = true
    )

    @Test
    fun startBeforeFirstWaypointRunsThroughStopWaypoint() {
        val result = SurveyDistanceCompiler.compile(
            listOf(
                distance(0, 11.5f),
                waypoint(1),
                waypoint(2),
                waypoint(3),
                distance(4, 0f)
            )
        )
        assertEquals(1, result.size)
        assertEquals(0, result.single().startWaypointIndex)
        assertEquals(2, result.single().endWaypointIndex)
        assertEquals(11.5, result.single().distanceM, 0.001)
    }

    @Test
    fun missingStopExtendsToFinalWaypoint() {
        val result = SurveyDistanceCompiler.compile(
            listOf(
                waypoint(0),
                distance(1, 9.0f),
                waypoint(2),
                waypoint(3)
            )
        )
        assertEquals(1, result.size)
        assertEquals(0, result.single().startWaypointIndex)
        assertEquals(2, result.single().endWaypointIndex)
    }

    @Test
    fun replacementDistanceClosesPreviousRange() {
        val result = SurveyDistanceCompiler.compile(
            listOf(
                waypoint(0),
                distance(1, 12f),
                waypoint(2),
                distance(3, 8f),
                waypoint(4),
                distance(5, 0f)
            )
        )
        assertEquals(2, result.size)
        assertEquals(12.0, result[0].distanceM, 0.001)
        assertEquals(0, result[0].startWaypointIndex)
        assertEquals(1, result[0].endWaypointIndex)
        assertEquals(8.0, result[1].distanceM, 0.001)
        assertEquals(1, result[1].startWaypointIndex)
        assertEquals(2, result[1].endWaypointIndex)
    }

    @Test
    fun immediateTriggerAndCameraIdSurviveCompilation() {
        val result = SurveyDistanceCompiler.compile(
            listOf(
                waypoint(0),
                distance(1, 10f, triggerNow = 1f, cameraId = 1f),
                waypoint(2),
                distance(3, 0f)
            )
        )
        assertTrue(result.single().triggerImmediately)
        assertEquals(1, result.single().targetCameraId)
    }
}
