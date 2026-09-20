package com.lyrebird.rc.logger

import com.lyrebird.rc.controller.Payload
import java.io.File
import org.json.JSONArray
import org.json.JSONObject

internal enum class SurveyRtkQuality {
    FIXED,
    FLOAT,
    STALE,
    MISSING
}

internal data class SurveyResolvedCapture(
    val sequence: Int,
    val capture: SurveyCaptureRecord,
    val media: Payload.ResolvedMedia?,
    val rtkQuality: SurveyRtkQuality
)

internal data class SurveyQualitySummary(
    val totalCaptures: Int,
    val resolvedFiles: Int,
    val unresolvedFiles: Int,
    val fixed: Int,
    val float: Int,
    val stale: Int,
    val missingRtk: Int
) {
    val fixedRatio: Double
        get() = if (totalCaptures == 0) 0.0 else fixed.toDouble() / totalCaptures

    val usableRtkRatio: Double
        get() = if (totalCaptures == 0) 0.0 else (fixed + float).toDouble() / totalCaptures
}

internal data class SurveyReportFiles(
    val csv: File,
    val summaryJson: File
)

/**
 * Produces WebODM-friendly capture metadata and a compact survey quality summary.
 *
 * No Android or DJI calls live here, which keeps classification/CSV generation unit-testable.
 */
internal object SurveyReportWriter {

    fun classify(record: SurveyCaptureRecord): SurveyRtkQuality = when {
        record.rtkFix == "STALE" -> SurveyRtkQuality.STALE
        record.rtkHealthy && record.rtkFix == "FIXED" -> SurveyRtkQuality.FIXED
        record.rtkHealthy && record.rtkFix == "FLOAT" -> SurveyRtkQuality.FLOAT
        else -> SurveyRtkQuality.MISSING
    }

    fun reconcile(
        captures: List<SurveyCaptureRecord>,
        mediaByIndex: Map<Int, List<Payload.ResolvedMedia>>
    ): List<SurveyResolvedCapture> =
        captures.mapIndexed { index, capture ->
            val candidates = capture.mediaIndex?.let(mediaByIndex::get).orEmpty()
            SurveyResolvedCapture(
                sequence = index + 1,
                capture = capture,
                media = chooseMedia(capture.lens, candidates),
                rtkQuality = classify(capture)
            )
        }

    fun summarize(rows: List<SurveyResolvedCapture>): SurveyQualitySummary =
        SurveyQualitySummary(
            totalCaptures = rows.size,
            resolvedFiles = rows.count { it.media != null },
            unresolvedFiles = rows.count { it.media == null },
            fixed = rows.count { it.rtkQuality == SurveyRtkQuality.FIXED },
            float = rows.count { it.rtkQuality == SurveyRtkQuality.FLOAT },
            stale = rows.count { it.rtkQuality == SurveyRtkQuality.STALE },
            missingRtk = rows.count { it.rtkQuality == SurveyRtkQuality.MISSING }
        )

    /**
     * Write files next to the active/current flight JSONL log.
     *
     * Example:
     *   10-31-02_m3e.jsonl
     *   10-31-02_m3e_captures.csv
     *   10-31-02_m3e_survey-summary.json
     */
    fun write(
        flightLogPath: String,
        captures: List<SurveyCaptureRecord>,
        mediaByIndex: Map<Int, List<Payload.ResolvedMedia>>,
        finishReason: String
    ): SurveyReportFiles {
        val flightLog = File(flightLogPath)
        val dir = flightLog.parentFile
            ?: error("Flight log has no parent directory: $flightLogPath")
        dir.mkdirs()

        val base = flightLog.nameWithoutExtension
        val rows = reconcile(captures, mediaByIndex)
        val summary = summarize(rows)

        val csvFile = File(dir, "${base}_captures.csv")
        val summaryFile = File(dir, "${base}_survey-summary.json")

        csvFile.writeText(toCsv(rows))
        summaryFile.writeText(toSummaryJson(rows, summary, finishReason).toString(2))
        return SurveyReportFiles(csvFile, summaryFile)
    }

    private fun chooseMedia(
        lens: String,
        candidates: List<Payload.ResolvedMedia>
    ): Payload.ResolvedMedia? {
        if (candidates.size <= 1) return candidates.firstOrNull()
        val normalized = lens.uppercase()
        return when {
            "INFRARED" in normalized || "THERMAL" in normalized ->
                candidates.firstOrNull { "_T." in it.fileName.uppercase() }
            "ZOOM" in normalized ->
                candidates.firstOrNull { "_Z." in it.fileName.uppercase() }
            "WIDE" in normalized || "VISIBLE" in normalized || "RGB" in normalized ->
                candidates.firstOrNull {
                    val name = it.fileName.uppercase()
                    "_W." in name || "_V." in name || "_D." in name
                }
            else -> null
        } ?: candidates.firstOrNull()
    }

    private fun toCsv(rows: List<SurveyResolvedCapture>): String {
        val header = listOf(
            "seq", "event_time_ms", "media_index", "file_name", "file_size_bytes", "file_type",
            "media_resolved", "lens", "rtk_quality", "rtk_fix", "rtk_healthy", "rtk_age_ms",
            "latitude", "longitude", "altitude_asl_m", "altitude_agl_m",
            "rtk_latitude", "rtk_longitude", "rtk_altitude_m",
            "rtk_std_latitude_m", "rtk_std_longitude_m", "rtk_std_altitude_m",
            "heading_deg", "aircraft_roll_deg", "aircraft_pitch_deg", "aircraft_yaw_deg",
            "gimbal_roll_deg", "gimbal_pitch_deg", "gimbal_yaw_deg",
            "gimbal_joint_roll_deg", "gimbal_joint_pitch_deg", "gimbal_joint_yaw_deg",
            "rtk_source", "flight_mode"
        )

        return buildString {
            appendLine(header.joinToString(","))
            rows.forEach { row ->
                val c = row.capture
                appendLine(
                    listOf(
                        row.sequence,
                        c.eventEpochMs,
                        c.mediaIndex,
                        row.media?.fileName,
                        row.media?.sizeBytes,
                        row.media?.fileType,
                        row.media != null,
                        c.lens,
                        row.rtkQuality.name,
                        c.rtkFix,
                        c.rtkHealthy,
                        c.rtkAgeMs.takeUnless { it == Long.MAX_VALUE },
                        c.latitudeDeg,
                        c.longitudeDeg,
                        c.altitudeAslM,
                        c.altitudeAglM,
                        c.rtkLatitudeDeg,
                        c.rtkLongitudeDeg,
                        c.rtkAltitudeM,
                        c.rtkStdLatitudeM,
                        c.rtkStdLongitudeM,
                        c.rtkStdAltitudeM,
                        c.headingDeg,
                        c.aircraftRollDeg,
                        c.aircraftPitchDeg,
                        c.aircraftYawDeg,
                        c.gimbalRollDeg,
                        c.gimbalPitchDeg,
                        c.gimbalYawDeg,
                        c.gimbalJointRollDeg,
                        c.gimbalJointPitchDeg,
                        c.gimbalJointYawDeg,
                        c.rtkSource,
                        c.flightMode
                    ).joinToString(",") { csv(it) }
                )
            }
        }
    }

    private fun toSummaryJson(
        rows: List<SurveyResolvedCapture>,
        summary: SurveyQualitySummary,
        finishReason: String
    ): JSONObject = JSONObject().apply {
        put("schemaVersion", 1)
        put("finishReason", finishReason)
        put("totalCaptures", summary.totalCaptures)
        put("resolvedFiles", summary.resolvedFiles)
        put("unresolvedFiles", summary.unresolvedFiles)
        put("rtkFixed", summary.fixed)
        put("rtkFloat", summary.float)
        put("rtkStale", summary.stale)
        put("rtkMissing", summary.missingRtk)
        put("rtkFixedRatio", summary.fixedRatio)
        put("rtkUsableRatio", summary.usableRtkRatio)

        val problems = JSONArray()
        rows.filter { it.media == null || it.rtkQuality != SurveyRtkQuality.FIXED }
            .forEach { row ->
                problems.put(
                    JSONObject().apply {
                        put("seq", row.sequence)
                        row.capture.mediaIndex?.let { put("mediaIndex", it) }
                        row.media?.fileName?.let { put("fileName", it) }
                        put("mediaResolved", row.media != null)
                        put("rtkQuality", row.rtkQuality.name)
                        put("rtkFix", row.capture.rtkFix)
                        if (row.capture.rtkAgeMs != Long.MAX_VALUE) {
                            put("rtkAgeMs", row.capture.rtkAgeMs)
                        }
                    }
                )
            }
        put("problemCaptures", problems)
    }

    private fun csv(value: Any?): String {
        if (value == null) return ""
        val raw = value.toString()
        return if (raw.any { it == ',' || it == '"' || it == '\n' || it == '\r' }) {
            "\"" + raw.replace("\"", "\"\"") + "\""
        } else {
            raw
        }
    }
}
