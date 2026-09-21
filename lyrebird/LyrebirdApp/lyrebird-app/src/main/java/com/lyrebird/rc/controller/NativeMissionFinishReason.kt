package com.lyrebird.rc.controller

/**
 * Why a DJI-native wayline stopped.
 *
 * MSDK 5.18 can emit FINISHED both for a natural completion and after stopMission(), so the
 * execute-state alone is not enough to decide whether a survey actually completed.
 */
internal enum class NativeMissionFinishReason(
    val completed: Boolean,
    val reportValue: String
) {
    COMPLETED(true, "mission_finished"),
    STOPPED(false, "mission_stopped"),
    INTERRUPTED(false, "mission_interrupted"),
    DISCONNECTED(false, "mission_disconnected"),
    NOT_SUPPORTED(false, "mission_not_supported"),
    START_FAILED(false, "mission_start_failed"),
    UPLOAD_FAILED(false, "mission_upload_failed"),
    INVALID_MISSION(false, "mission_invalid"),
    REPLACED(false, "mission_replaced")
}

internal object NativeMissionFinishClassifier {
    /**
     * Returns null for a non-terminal state. A user-requested pause is deliberately non-terminal:
     * MSDK reports it as INTERRUPTED, but the mission may subsequently resume.
     */
    fun classify(
        stateName: String,
        stopRequested: Boolean,
        pauseRequested: Boolean
    ): NativeMissionFinishReason? = when (stateName) {
        "FINISHED" ->
            if (stopRequested) NativeMissionFinishReason.STOPPED
            else NativeMissionFinishReason.COMPLETED
        "INTERRUPTED" ->
            if (pauseRequested) null
            else NativeMissionFinishReason.INTERRUPTED
        "DISCONNECTED" -> NativeMissionFinishReason.DISCONNECTED
        "NOT_SUPPORTED" -> NativeMissionFinishReason.NOT_SUPPORTED
        else -> null
    }
}
