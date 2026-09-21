package com.lyrebird.rc

/**
 * Decide whether a newly discovered ground-station peer may start or retarget video publishing.
 *
 * Telemetry TCP and MAVLink discovery can report different peers only milliseconds apart. While
 * the first native DJI stream is still STARTING, ILiveStreamManager.isStreaming is false, so the
 * old guard treated the publisher as idle and allowed the second peer to start another stream.
 */
internal fun shouldStartStreamingForPeer(
    currentClientIp: String?,
    candidateClientIp: String,
    publisherHealthy: Boolean,
    nativeTransitionActive: Boolean,
    nativeStreaming: Boolean,
    webRtcSessionRunning: Boolean
): Boolean {
    if (currentClientIp == null) return true

    val nativeBusy = nativeTransitionActive || nativeStreaming

    if (currentClientIp == candidateClientIp) {
        // Preserve the existing stale-WHIP recovery: the same client may retry when WebRTC is
        // running but not actually publishing. Native transitions/streams, however, must not be
        // duplicated.
        return !publisherHealthy && !nativeBusy
    }

    // Never let another discovered peer hijack a stream that is starting, running, stopping, or
    // has an active WebRTC session. Manual configuration restarts bypass this discovery policy.
    return !publisherHealthy && !nativeBusy && !webRtcSessionRunning
}
