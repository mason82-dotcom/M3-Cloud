package com.lyrebird.rc.mavlink

import org.junit.Assert.assertEquals
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
        param3: Float = 0f,
        param4: Float = 0f
    ) = MissionItem(
        seq = seq,
        command = Mav.CMD_DO_SET_CAM_TRIGG_DIST,
        param1 = metres,
        param2 = 0f,
        param3 = param3,
        param4 = param4,
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
    fun param3AndParam4ArePreservedButNotInterpreted() {
        val result = SurveyDistanceCompiler.compile(
            listOf(
                waypoint(0),
                distance(1, 10f, param3 = 2.75f, param4 = 42f),
                waypoint(2),
                distance(3, 0f)
            )
        )
        assertEquals(2.75, result.single().param3Raw ?: Double.NaN, 0.001)
        assertEquals(42.0, result.single().param4Raw ?: Double.NaN, 0.001)
    }

    @Test
    fun arbitraryFiniteParam3DoesNotRejectMission() {
        val result = SurveyDistanceCompiler.compile(
            listOf(
                distance(0, 12f, param3 = 0.35f, param4 = 99f),
                waypoint(1),
                waypoint(2)
            )
        )
        assertEquals(1, result.size)
        assertEquals(12.0, result.single().distanceM, 0.001)
    }
}
