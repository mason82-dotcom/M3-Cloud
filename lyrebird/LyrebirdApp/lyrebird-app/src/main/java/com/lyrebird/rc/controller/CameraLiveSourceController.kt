package com.lyrebird.rc.controller

import dji.sdk.keyvalue.key.CameraKey
import dji.sdk.keyvalue.key.DJIKey
import dji.sdk.keyvalue.key.KeyTools
import dji.sdk.keyvalue.value.camera.CameraMode
import dji.sdk.keyvalue.value.camera.CameraVideoStreamSourceType
import dji.sdk.keyvalue.value.common.ComponentIndexType
import dji.v5.common.callback.CommonCallbacks
import dji.v5.common.error.IDJIError
import dji.v5.et.listen
import dji.v5.manager.KeyManager
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

internal data class CameraLiveSourceReadback(
    val source: String?,
    val readStatus: String
) {
    fun toJson(): String = JSONObject()
        .put("source", source ?: JSONObject.NULL)
        .put("readStatus", readStatus)
        .toString()
}

internal data class CameraLiveSourceSetResult(
    val requested: String,
    val setStatus: String,
    val source: String?,
    val readStatus: String,
    val error: String? = null
) {
    fun toJson(): String = JSONObject()
        .put("requested", requested)
        .put("setStatus", setStatus)
        .put("source", source ?: JSONObject.NULL)
        .put("readStatus", readStatus)
        .put("error", error ?: JSONObject.NULL)
        .toString()
}

internal enum class CameraLiveSourceAvailability {
    READY,
    NOT_READY,
    SOURCE_NOT_AVAILABLE
}

internal fun classifyCameraLiveSourceAvailability(
    requested: String,
    rangeReadSucceeded: Boolean,
    supportedSourceNames: List<String>
): CameraLiveSourceAvailability = when {
    !rangeReadSucceeded || supportedSourceNames.isEmpty() ->
        CameraLiveSourceAvailability.NOT_READY
    requested !in supportedSourceNames ->
        CameraLiveSourceAvailability.SOURCE_NOT_AVAILABLE
    else ->
        CameraLiveSourceAvailability.READY
}

/**
 * Isolated MSDK access for the active camera live-view source.
 *
 * This deliberately bypasses UI widgets and stream surfaces so field tests can distinguish a
 * camera/SDK fallback from a Lyrebird UI action. All reads and writes use real KeyManager
 * callbacks instead of relying on the synchronous key cache.
 */
internal object CameraLiveSourceController {
    private const val READ_TIMEOUT_MS = 1_500L
    private const val READ_ATTEMPTS = 2
    private const val READ_RETRY_DELAY_MS = 200L
    private const val SOURCE_RANGE_TIMEOUT_MS = 2_000L
    private const val SET_CALLBACK_TIMEOUT_MS = 6_000L
    private const val READBACK_SETTLE_TIMEOUT_MS = 2_500L
    private const val READBACK_POLL_MS = 250L
    private const val HISTORY_LIMIT = 64

    private data class SourceEvent(
        val timestampMs: Long,
        val event: String,
        val value: String?,
        val reason: String?
    )

    private val historyLock = Any()
    private val history = ArrayDeque<SourceEvent>()

    private fun recordEvent(event: String, value: String? = null, reason: String? = null) {
        synchronized(historyLock) {
            if (history.size >= HISTORY_LIMIT) history.removeFirst()
            history.addLast(
                SourceEvent(
                    timestampMs = System.currentTimeMillis(),
                    event = event,
                    value = value,
                    reason = reason
                )
            )
        }
    }

    fun historyJson(): String {
        val events = synchronized(historyLock) { history.toList() }
        return JSONObject()
            .put("events", JSONArray().apply {
                events.forEach { item ->
                    put(
                        JSONObject()
                            .put("timestampMs", item.timestampMs)
                            .put("event", item.event)
                            .put("value", item.value ?: JSONObject.NULL)
                            .put("reason", item.reason ?: JSONObject.NULL)
                    )
                }
            })
            .toString()
    }

    @Volatile private var cachedSource: String? = null
    @Volatile private var cachedReadStatus: String = "not_reported"
    @Volatile private var trackingStarted: Boolean = false

    private fun updateCachedSource(
        source: CameraVideoStreamSourceType?,
        event: String = "cache-update",
        reason: String? = null
    ) {
        val previous = cachedSource
        if (source != null) {
            cachedSource = source.name
            cachedReadStatus = "confirmed"
            if (previous != source.name || event != "listener") {
                recordEvent(event, source.name, reason)
            }
        } else {
            cachedReadStatus = if (cachedSource != null) "stale" else "not_reported"
            recordEvent(event, null, reason)
        }
    }

    private fun markCachedSourceUnavailable(reason: String? = null) {
        cachedReadStatus = if (cachedSource != null) "stale" else "not_reported"
        recordEvent("source-unavailable", cachedSource, reason)
    }

    @Synchronized
    private fun ensureTracking() {
        if (trackingStarted) return

        val sourceKey = key()
        sourceKey.listen(this) { source ->
            updateCachedSource(source, event = "listener", reason = "msdk-key-change")
        }
        val modeKey: DJIKey<CameraMode> =
            KeyTools.createKey(CameraKey.KeyCameraMode, ComponentIndexType.LEFT_OR_MAIN)
        modeKey.listen(this) { mode ->
            recordEvent("camera-mode", mode?.name, "msdk-key-change")
        }
        trackingStarted = true
        recordEvent("tracking-start")

        KeyManager.getInstance().getValue(
            sourceKey,
            object : CommonCallbacks.CompletionCallbackWithParam<CameraVideoStreamSourceType> {
                override fun onSuccess(source: CameraVideoStreamSourceType?) {
                    updateCachedSource(source, event = "seed-read", reason = "tracking-start")
                }

                override fun onFailure(error: IDJIError) {
                    markCachedSourceUnavailable("tracking-start:${describeError(error)}")
                }
            }
        )
    }

    /** Prime the listener/cache without blocking the caller. */
    fun warmCache() {
        ensureTracking()
    }

    /**
     * Non-blocking live-source snapshot for frequently polled settings endpoints.
     *
     * The value is seeded asynchronously from KeyManager and then maintained by the key listener.
     * A stale status preserves the last DJI-confirmed source across transient key unavailability.
     */
    fun cachedReadback(): CameraLiveSourceReadback {
        ensureTracking()
        return CameraLiveSourceReadback(cachedSource, cachedReadStatus)
    }

    private fun key(
        index: ComponentIndexType = ComponentIndexType.LEFT_OR_MAIN
    ): DJIKey<CameraVideoStreamSourceType> =
        KeyTools.createKey(CameraKey.KeyCameraVideoStreamSource, index)

    private fun sourceRangeKey(
        index: ComponentIndexType = ComponentIndexType.LEFT_OR_MAIN
    ): DJIKey<List<CameraVideoStreamSourceType>> =
        KeyTools.createKey(CameraKey.KeyCameraVideoStreamSourceRange, index)

    private data class ReadAttempt<T>(
        val completed: Boolean,
        val success: Boolean,
        val value: T?,
        val error: String?
    )

    private fun describeError(error: IDJIError?): String {
        if (error == null) return "DJI error: null"

        val type = runCatching { error.errorType()?.toString() }
            .getOrNull()
            ?.takeIf { it.isNotBlank() }
        val code = runCatching { error.errorCode()?.toString() }
            .getOrNull()
            ?.takeIf { it.isNotBlank() }
        val description = runCatching { error.description() }
            .getOrNull()
            ?.trim()
            ?.takeIf { it.isNotBlank() }
        val raw = runCatching { error.toString() }
            .getOrNull()
            ?.takeIf { it.isNotBlank() }

        return buildString {
            append("type=")
            append(type ?: "null")
            append(",code=")
            append(code ?: "null")
            append(",description=")
            append(description ?: "null")
            append(",raw=")
            append(raw ?: "null")
        }
    }

    private fun <T> readOnce(
        readKey: DJIKey<T>,
        timeoutMs: Long
    ): ReadAttempt<T> {
        val latch = CountDownLatch(1)
        val value = AtomicReference<T?>(null)
        val success = AtomicBoolean(false)
        val errorText = AtomicReference<String?>(null)

        KeyManager.getInstance().getValue(
            readKey,
            object : CommonCallbacks.CompletionCallbackWithParam<T> {
                override fun onSuccess(result: T?) {
                    value.set(result)
                    success.set(true)
                    latch.countDown()
                }

                override fun onFailure(error: IDJIError) {
                    errorText.set(describeError(error))
                    latch.countDown()
                }
            }
        )

        val completed = try {
            latch.await(timeoutMs, TimeUnit.MILLISECONDS)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            false
        }

        return ReadAttempt(
            completed = completed,
            success = completed && success.get(),
            value = value.get(),
            error = when {
                !completed -> "callback timeout after ${timeoutMs}ms"
                else -> errorText.get()
            }
        )
    }

    private fun readCurrentOnce(
        index: ComponentIndexType,
        timeoutMs: Long = READ_TIMEOUT_MS,
        eventReason: String = "explicit-read"
    ): CameraLiveSourceReadback {
        val attempt = readOnce(key(index), timeoutMs)
        if (attempt.success) {
            val current = attempt.value
            if (index == ComponentIndexType.LEFT_OR_MAIN) {
                updateCachedSource(current, event = "read-ok", reason = eventReason)
            }
            return CameraLiveSourceReadback(
                source = current?.name,
                readStatus = "OK"
            )
        }
        return CameraLiveSourceReadback(null, "UNAVAILABLE")
    }

    fun readCurrent(
        index: ComponentIndexType = ComponentIndexType.LEFT_OR_MAIN
    ): CameraLiveSourceReadback {
        repeat(READ_ATTEMPTS) { attempt ->
            val readback = readCurrentOnce(index)
            if (readback.readStatus == "OK") return readback

            if (attempt < READ_ATTEMPTS - 1) {
                try {
                    Thread.sleep(READ_RETRY_DELAY_MS)
                } catch (_: InterruptedException) {
                    Thread.currentThread().interrupt()
                    return CameraLiveSourceReadback(null, "UNAVAILABLE")
                }
            }
        }

        if (index == ComponentIndexType.LEFT_OR_MAIN) {
            markCachedSourceUnavailable("explicit-read")
        }
        return CameraLiveSourceReadback(null, "UNAVAILABLE")
    }

    private fun confirmRequestedSource(
        requested: CameraVideoStreamSourceType,
        index: ComponentIndexType
    ): CameraLiveSourceReadback {
        val deadline = System.currentTimeMillis() + READBACK_SETTLE_TIMEOUT_MS
        var lastReadback = CameraLiveSourceReadback(null, "UNAVAILABLE")

        do {
            lastReadback = readCurrentOnce(
                index,
                timeoutMs = READ_TIMEOUT_MS,
                eventReason = "set-confirm-read"
            )
            if (
                lastReadback.readStatus == "OK" &&
                lastReadback.source == requested.name
            ) {
                if (index == ComponentIndexType.LEFT_OR_MAIN) {
                    recordEvent(
                        "set-confirmed",
                        lastReadback.source,
                        "readback"
                    )
                }
                return lastReadback
            }

            val remaining = deadline - System.currentTimeMillis()
            if (remaining <= 0L) break

            try {
                Thread.sleep(minOf(READBACK_POLL_MS, remaining))
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
                break
            }
        } while (System.currentTimeMillis() < deadline)

        return lastReadback
    }

    fun setAndReadback(
        rawSource: String,
        index: ComponentIndexType = ComponentIndexType.LEFT_OR_MAIN,
        reason: String = "unspecified"
    ): CameraLiveSourceSetResult {
        if (index == ComponentIndexType.LEFT_OR_MAIN) ensureTracking()

        val requested = rawSource.trim().uppercase()
        if (index == ComponentIndexType.LEFT_OR_MAIN) {
            recordEvent("set-request", requested, reason)
        }

        val source = CameraVideoStreamSourceType.values()
            .firstOrNull { it.name == requested }
            ?: run {
                val readback = readCurrent(index)
                return CameraLiveSourceSetResult(
                    requested = requested,
                    setStatus = "INVALID_SOURCE",
                    source = readback.source,
                    readStatus = readback.readStatus,
                    error = "Unknown camera video stream source"
                )
            }

        // Gate writes on the camera's *current* MSDK-reported source range. This avoids firing
        // KeyCameraVideoStreamSource while the camera type/lens table is still coming up.
        val rangeRead = readOnce(sourceRangeKey(index), SOURCE_RANGE_TIMEOUT_MS)
        val supportedNames = rangeRead.value.orEmpty().map { it.name }
        when (
            classifyCameraLiveSourceAvailability(
                requested = requested,
                rangeReadSucceeded = rangeRead.success,
                supportedSourceNames = supportedNames
            )
        ) {
            CameraLiveSourceAvailability.NOT_READY -> {
                val readback = readCurrent(index)
                if (index == ComponentIndexType.LEFT_OR_MAIN) {
                    recordEvent(
                        "set-skipped-not-ready",
                        requested,
                        "$reason:range=${supportedNames.joinToString()}:error=${rangeRead.error}"
                    )
                }
                return CameraLiveSourceSetResult(
                    requested = requested,
                    setStatus = "NOT_READY",
                    source = readback.source,
                    readStatus = readback.readStatus,
                    error = rangeRead.error ?: "Camera live-source range is not ready"
                )
            }

            CameraLiveSourceAvailability.SOURCE_NOT_AVAILABLE -> {
                val readback = readCurrent(index)
                if (index == ComponentIndexType.LEFT_OR_MAIN) {
                    recordEvent(
                        "set-skipped-unavailable",
                        requested,
                        "$reason:range=${supportedNames.joinToString()}"
                    )
                }
                return CameraLiveSourceSetResult(
                    requested = requested,
                    setStatus = "SOURCE_NOT_AVAILABLE",
                    source = readback.source,
                    readStatus = readback.readStatus,
                    error = "Source not in current camera range: ${supportedNames.joinToString()}"
                )
            }

            CameraLiveSourceAvailability.READY -> Unit
        }

        // Exactly one MSDK SET per call. The outer restore loop in FlightDeckActivity owns retries.
        // This prevents overlapping KeyCameraVideoStreamSource transactions when DJI callbacks are
        // delayed for several seconds during M3M camera startup.
        val latch = CountDownLatch(1)
        val callbackSuccess = AtomicBoolean(false)
        val callbackFailed = AtomicBoolean(false)
        val callbackError = AtomicReference<String?>(null)

        KeyManager.getInstance().setValue(
            key(index),
            source,
            object : CommonCallbacks.CompletionCallback {
                override fun onSuccess() {
                    if (index == ComponentIndexType.LEFT_OR_MAIN) {
                        recordEvent("set-callback-ok", requested, reason)
                    }
                    callbackSuccess.set(true)
                    latch.countDown()
                }

                override fun onFailure(error: IDJIError) {
                    val diagnostic = describeError(error)
                    if (index == ComponentIndexType.LEFT_OR_MAIN) {
                        recordEvent(
                            "set-callback-failed",
                            requested,
                            "$reason:$diagnostic"
                        )
                    }
                    callbackFailed.set(true)
                    callbackError.set(diagnostic)
                    latch.countDown()
                }
            }
        )

        val completed = try {
            latch.await(SET_CALLBACK_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            false
        }

        val callbackStatus = when {
            !completed -> "TIMEOUT"
            callbackSuccess.get() -> "OK"
            callbackFailed.get() -> "FAILED"
            else -> "FAILED"
        }

        // The authoritative state is the source DJI reports after the request. A delayed or failed
        // callback must not make Lyrebird report failure if the camera itself confirms the source.
        val readback = confirmRequestedSource(source, index)
        val confirmed =
            readback.readStatus == "OK" &&
                readback.source == requested

        if (confirmed) {
            val diagnostic = when (callbackStatus) {
                "OK" -> null
                "TIMEOUT" ->
                    "MSDK set callback timed out after ${SET_CALLBACK_TIMEOUT_MS}ms; source confirmed by readback"
                else ->
                    callbackError.get()?.let { "$it; source confirmed by readback" }
                        ?: "MSDK set callback failed; source confirmed by readback"
            }
            if (index == ComponentIndexType.LEFT_OR_MAIN) {
                recordEvent(
                    "set-readback",
                    readback.source,
                    "$reason:requested=$requested,callback=$callbackStatus,status=${readback.readStatus}"
                )
            }
            return CameraLiveSourceSetResult(
                requested = requested,
                setStatus = "OK",
                source = readback.source,
                readStatus = readback.readStatus,
                error = diagnostic
            )
        }

        val finalStatus = if (callbackStatus == "OK") {
            "READBACK_MISMATCH"
        } else {
            callbackStatus
        }
        val finalError = when {
            callbackError.get() != null -> callbackError.get()
            callbackStatus == "TIMEOUT" ->
                "MSDK set callback timed out after ${SET_CALLBACK_TIMEOUT_MS}ms"
            callbackStatus == "OK" ->
                "MSDK callback succeeded but requested source was not confirmed"
            else ->
                "MSDK set failed"
        }

        if (index == ComponentIndexType.LEFT_OR_MAIN) {
            recordEvent(
                "set-final-readback",
                readback.source,
                "$reason:requested=$requested,setStatus=$finalStatus,status=${readback.readStatus}"
            )
        }
        return CameraLiveSourceSetResult(
            requested = requested,
            setStatus = finalStatus,
            source = readback.source,
            readStatus = readback.readStatus,
            error = finalError
        )
    }
}
