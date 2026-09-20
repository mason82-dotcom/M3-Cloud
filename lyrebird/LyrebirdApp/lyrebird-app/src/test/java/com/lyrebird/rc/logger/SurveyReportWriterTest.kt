package com.lyrebird.rc.logger

import com.lyrebird.rc.controller.Payload
import java.nio.file.Files
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SurveyReportWriterTest {

    private fun capture(
        index: Int?,
        fix: String,
        healthy: Boolean = true,
        ageMs: Long = 100
    ) = SurveyCaptureRecord(
        eventEpochMs = 1_789_738_938_481L + (index ?: 0),
        mediaIndex = index,
        lens = "WIDE",
        latitudeDeg = 49.1,
        longitudeDeg = 8.6,
        altitudeAslM = 143.0,
        altitudeAglM = 70.0,
        satelliteCount = 28,
        headingDeg = 90.0,
        aircraftRollDeg = 0.0,
        aircraftPitchDeg = 0.0,
        aircraftYawDeg = 90.0,
        gimbalRollDeg = 0.0,
        gimbalPitchDeg = -90.0,
        gimbalYawDeg = 90.0,
        gimbalJointRollDeg = 0.0,
        gimbalJointPitchDeg = -90.0,
        gimbalJointYawDeg = 0.0,
        rtkEnabled = true,
        rtkHealthy = healthy,
        rtkFix = fix,
        rtkRawFix = fix,
        rtkAgeMs = ageMs,
        rtkLatitudeDeg = 49.1,
        rtkLongitudeDeg = 8.6,
        rtkAltitudeM = 143.0,
        rtkStdLatitudeM = 0.01,
        rtkStdLongitudeM = 0.01,
        rtkStdAltitudeM = 0.02,
        rtkSource = "CUSTOM_NETWORK_SERVICE",
        flightMode = "WAYPOINT"
    )

    @Test
    fun qualityClassificationUsesOnlyUsableFreshRtkAsFixedOrFloat() {
        assertEquals(SurveyRtkQuality.FIXED, SurveyReportWriter.classify(capture(1, "FIXED")))
        assertEquals(SurveyRtkQuality.FLOAT, SurveyReportWriter.classify(capture(2, "FLOAT")))
        assertEquals(SurveyRtkQuality.STALE, SurveyReportWriter.classify(capture(3, "STALE")))
        assertEquals(
            SurveyRtkQuality.MISSING,
            SurveyReportWriter.classify(capture(4, "FIXED", healthy = false))
        )
        assertEquals(
            SurveyRtkQuality.MISSING,
            SurveyReportWriter.classify(capture(5, "SINGLE"))
        )
    }

    @Test
    fun summarySeparatesMediaResolutionFromRtkQuality() {
        val captures = listOf(
            capture(10, "FIXED"),
            capture(11, "FLOAT"),
            capture(12, "STALE"),
            capture(null, "UNKNOWN", healthy = false, ageMs = Long.MAX_VALUE)
        )
        val media = mapOf(
            10 to listOf(Payload.ResolvedMedia(10, "DJI_0010.JPG", 123L, "JPEG")),
            11 to listOf(Payload.ResolvedMedia(11, "DJI_0011.JPG", 124L, "JPEG"))
        )
        val summary = SurveyReportWriter.summarize(
            SurveyReportWriter.reconcile(captures, media)
        )

        assertEquals(4, summary.totalCaptures)
        assertEquals(2, summary.resolvedFiles)
        assertEquals(2, summary.unresolvedFiles)
        assertEquals(1, summary.fixed)
        assertEquals(1, summary.float)
        assertEquals(1, summary.stale)
        assertEquals(1, summary.missingRtk)
        assertEquals(0.25, summary.fixedRatio, 0.0001)
        assertEquals(0.50, summary.usableRtkRatio, 0.0001)
    }

    @Test
    fun writerCreatesCsvAndJsonBesideFlightLog() {
        val dir = Files.createTempDirectory("lyrebird-survey").toFile()
        val flightLog = dir.resolve("10-30-00_m3e.jsonl").apply { writeText("") }
        val captures = listOf(capture(20, "FIXED"))
        val media = mapOf(
            20 to listOf(Payload.ResolvedMedia(20, "DJI_0020.JPG", 1000L, "JPEG"))
        )

        val files = SurveyReportWriter.write(
            flightLog.absolutePath,
            captures,
            media,
            "mission_finished"
        )

        assertTrue(files.csv.isFile)
        assertTrue(files.summaryJson.isFile)
        assertTrue(files.csv.readText().contains("DJI_0020.JPG"))
        assertTrue(files.csv.readText().contains("FIXED"))
        assertTrue(files.summaryJson.readText().contains("\"rtkFixed\": 1"))
        assertFalse(files.summaryJson.readText().contains("\"unresolvedFiles\": 1"))
    }
}
