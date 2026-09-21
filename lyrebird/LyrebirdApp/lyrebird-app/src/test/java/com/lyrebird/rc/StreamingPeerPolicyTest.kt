package com.lyrebird.rc

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StreamingPeerPolicyTest {

    @Test
    fun firstPeerMayStartPublishing() {
        assertTrue(
            shouldStartStreamingForPeer(
                currentClientIp = null,
                candidateClientIp = "192.168.178.45",
                publisherHealthy = false,
                nativeTransitionActive = false,
                nativeStreaming = false,
                webRtcSessionRunning = false
            )
        )
    }

    @Test
    fun samePeerCannotDuplicateNativeStart() {
        assertFalse(
            shouldStartStreamingForPeer(
                currentClientIp = "192.168.178.45",
                candidateClientIp = "192.168.178.45",
                publisherHealthy = false,
                nativeTransitionActive = true,
                nativeStreaming = false,
                webRtcSessionRunning = false
            )
        )
    }

    @Test
    fun secondPeerCannotRetargetNativeStartInProgress() {
        assertFalse(
            shouldStartStreamingForPeer(
                currentClientIp = "192.168.178.45",
                candidateClientIp = "192.168.178.23",
                publisherHealthy = false,
                nativeTransitionActive = true,
                nativeStreaming = false,
                webRtcSessionRunning = false
            )
        )
    }

    @Test
    fun secondPeerCannotRetargetWebRtcHandshake() {
        assertFalse(
            shouldStartStreamingForPeer(
                currentClientIp = "192.168.178.45",
                candidateClientIp = "192.168.178.23",
                publisherHealthy = false,
                nativeTransitionActive = false,
                nativeStreaming = false,
                webRtcSessionRunning = true
            )
        )
    }

    @Test
    fun samePeerMayRecoverStaleWhipPublisher() {
        assertTrue(
            shouldStartStreamingForPeer(
                currentClientIp = "192.168.178.45",
                candidateClientIp = "192.168.178.45",
                publisherHealthy = false,
                nativeTransitionActive = false,
                nativeStreaming = false,
                webRtcSessionRunning = true
            )
        )
    }
}
