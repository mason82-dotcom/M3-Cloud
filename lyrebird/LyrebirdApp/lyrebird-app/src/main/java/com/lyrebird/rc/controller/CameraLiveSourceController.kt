package com.lyrebird.rc.controller

import dji.sdk.keyvalue.key.CameraKey
import dji.sdk.keyvalue.key.DJIKey
import dji.sdk.keyvalue.key.KeyTools
import dji.sdk.keyvalue.value.camera.CameraVideoStreamSourceType
import dji.sdk.keyvalue.value.common.ComponentIndexType
import dji.v5.common.callback.CommonCallbacks
import dji.v5.common.error.IDJIError
import dji.v5.manager.KeyManager
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
                return CameraLiveSourceReadback(
                    source = value.get()?.name,
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
        return CameraLiveSourceReadback(null, "UNAVAILABLE")
    }

    fun setAndReadback(
        rawSource: String,
        index: ComponentIndexType = ComponentIndexType.LEFT_OR_MAIN
    ): CameraLiveSourceSetResult {
        val requested = rawSource.trim().uppercase()
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
                        success.set(true)
                        latch.countDown()
                    }

                    override fun onFailure(error: IDJIError) {
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
        return CameraLiveSourceSetResult(
            requested = requested,
            setStatus = lastStatus,
            source = readback.source,
            readStatus = readback.readStatus,
            error = lastError
        )
    }
}
