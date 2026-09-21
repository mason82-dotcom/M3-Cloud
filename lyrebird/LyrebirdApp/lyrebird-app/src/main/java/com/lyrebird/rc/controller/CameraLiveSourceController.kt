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

/**
 * Isolated MSDK access for the active camera live-view source.
 *
 * This deliberately bypasses UI widgets and stream surfaces so field tests can distinguish a
 * camera/SDK fallback from a Lyrebird UI action. All reads and writes use real KeyManager
 * callbacks instead of relying on the synchronous key cache.
 */
internal object CameraLiveSourceController {
    private const val TIMEOUT_MS = 1_000L
    private const val ATTEMPTS = 2
    private const val RETRY_DELAY_MS = 200L
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
                    markCachedSourceUnavailable("tracking-start:${error.description()}")
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

    fun readCurrent(
        index: ComponentIndexType = ComponentIndexType.LEFT_OR_MAIN
    ): CameraLiveSourceReadback {
        repeat(ATTEMPTS) { attempt ->
            val latch = CountDownLatch(1)
            val value = AtomicReference<CameraVideoStreamSourceType?>(null)
            val success = AtomicBoolean(false)

            KeyManager.getInstance().getValue(
                key(index),
                object : CommonCallbacks.CompletionCallbackWithParam<CameraVideoStreamSourceType> {
                    override fun onSuccess(source: CameraVideoStreamSourceType?) {
                        value.set(source)
                        success.set(true)
                        latch.countDown()
                    }

                    override fun onFailure(error: IDJIError) {
                        latch.countDown()
                    }
                }
            )

            val completed = try {
                latch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
                false
            }

            if (completed && success.get()) {
                val current = value.get()
                if (index == ComponentIndexType.LEFT_OR_MAIN) {
                    updateCachedSource(current, event = "read-ok", reason = "explicit-read")
                }
                return CameraLiveSourceReadback(
                    source = current?.name,
                    readStatus = "OK"
                )
            }
            if (attempt < ATTEMPTS - 1) {
                try {
                    Thread.sleep(RETRY_DELAY_MS)
                } catch (_: InterruptedException) {
                    Thread.currentThread().interrupt()
                    return CameraLiveSourceReadback(null, "UNAVAILABLE")
                }
            }
        }
        if (index == ComponentIndexType.LEFT_OR_MAIN) markCachedSourceUnavailable("explicit-read")
        return CameraLiveSourceReadback(null, "UNAVAILABLE")
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

        var lastStatus = "FAILED"
        var lastError: String? = null

        repeat(ATTEMPTS) { attempt ->
            val latch = CountDownLatch(1)
            val success = AtomicBoolean(false)
            val errorText = AtomicReference<String?>(null)

            KeyManager.getInstance().setValue(
                key(index),
                source,
                object : CommonCallbacks.CompletionCallback {
                    override fun onSuccess() {
                        if (index == ComponentIndexType.LEFT_OR_MAIN) {
                            recordEvent("set-callback-ok", requested, reason)
                        }
                        success.set(true)
                        latch.countDown()
                    }

                    override fun onFailure(error: IDJIError) {
                        if (index == ComponentIndexType.LEFT_OR_MAIN) {
                            recordEvent(
                                "set-callback-failed",
                                requested,
                                "$reason:${error.description()}"
                            )
                        }
                        errorText.set(error.description())
                        latch.countDown()
                    }
                }
            )

            val completed = try {
                latch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
                false
            }

            lastStatus = when {
                !completed -> "TIMEOUT"
                success.get() -> "OK"
                else -> "FAILED"
            }
            lastError = errorText.get()

            if (success.get()) {
                val readback = readCurrent(index)
                if (index == ComponentIndexType.LEFT_OR_MAIN) {
                    recordEvent(
                        "set-readback",
                        readback.source,
                        "$reason:requested=$requested,status=${readback.readStatus}"
                    )
                }
                return CameraLiveSourceSetResult(
                    requested = requested,
                    setStatus = "OK",
                    source = readback.source,
                    readStatus = readback.readStatus,
                    error = lastError
                )
            }

            if (attempt < ATTEMPTS - 1) {
                try {
                    Thread.sleep(RETRY_DELAY_MS)
                } catch (_: InterruptedException) {
                    Thread.currentThread().interrupt()
                    return CameraLiveSourceSetResult(
                        requested = requested,
                        setStatus = lastStatus,
                        source = null,
                        readStatus = "UNAVAILABLE",
                        error = lastError
                    )
                }
            }
        }

        val readback = readCurrent(index)
        if (index == ComponentIndexType.LEFT_OR_MAIN) {
            recordEvent(
                "set-final-readback",
                readback.source,
                "$reason:requested=$requested,setStatus=$lastStatus,status=${readback.readStatus}"
            )
        }
        return CameraLiveSourceSetResult(
            requested = requested,
            setStatus = lastStatus,
            source = readback.source,
            readStatus = readback.readStatus,
            error = lastError
        )
    }
}
