package com.lyrebird.rc.controller

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class NativeMissionFinishReasonTest {

    @Test
    fun naturalFinishedIsCompleted() {
        assertEquals(
            NativeMissionFinishReason.COMPLETED,
            NativeMissionFinishClassifier.classify("FINISHED", false, false)
        )
    }

    @Test
    fun finishedAfterStopIsNotSuccessfulCompletion() {
        assertEquals(
            NativeMissionFinishReason.STOPPED,
            NativeMissionFinishClassifier.classify("FINISHED", true, false)
        )
    }

    @Test
    fun userPauseInterruptedStateIsNonTerminal() {
        assertNull(NativeMissionFinishClassifier.classify("INTERRUPTED", false, true))
    }

    @Test
    fun unexplainedInterruptedStateIsFailure() {
        assertEquals(
            NativeMissionFinishReason.INTERRUPTED,
            NativeMissionFinishClassifier.classify("INTERRUPTED", false, false)
        )
    }

    @Test
    fun disconnectedAndUnsupportedAreExplicitFailures() {
        assertEquals(
            NativeMissionFinishReason.DISCONNECTED,
            NativeMissionFinishClassifier.classify("DISCONNECTED", false, false)
        )
        assertEquals(
            NativeMissionFinishReason.NOT_SUPPORTED,
            NativeMissionFinishClassifier.classify("NOT_SUPPORTED", false, false)
        )
    }
}
