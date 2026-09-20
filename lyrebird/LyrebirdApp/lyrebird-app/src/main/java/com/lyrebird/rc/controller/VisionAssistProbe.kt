package com.lyrebird.rc.controller

import dji.sdk.keyvalue.key.FlightControllerKey
import dji.sdk.keyvalue.key.KeyTools
import dji.sdk.keyvalue.value.common.ComponentIndexType
import dji.sdk.keyvalue.value.flightassistant.VisionAssistDirection
import dji.v5.common.callback.CommonCallbacks
import dji.v5.common.error.IDJIError
import dji.v5.manager.KeyManager
import dji.v5.manager.datacenter.MediaDataCenter
import dji.v5.manager.interfaces.ICameraStreamManager
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

internal data class VisionAssistSnapshot(
    val available: Boolean?,
    val streamAvailable: Boolean?,
    val motorsOn: Boolean?,
    val availableCameraIndices: List<String>,
    val streamEnabled: Boolean?,
    val enabled: Boolean?,
    val direction: String?,
    val directionRange: List<String>,
    val availabilityReadStatus: String,
    val statusReadStatus: String
) {
    fun toJsonObject(): JSONObject = JSONObject()
        .put("componentIndex", ComponentIndexType.VISION_ASSIST.name)
        .put("available", available ?: JSONObject.NULL)
        .put("streamAvailable", streamAvailable ?: JSONObject.NULL)
        .put("motorsOn", motorsOn ?: JSONObject.NULL)
        .put("availableCameraIndices", JSONArray(availableCameraIndices))
        .put("streamEnabled", streamEnabled ?: JSONObject.NULL)
        .put("enabled", enabled ?: JSONObject.NULL)
        .put("direction", direction ?: JSONObject.NULL)
        .put("directionRange", JSONArray(directionRange))
        .put("availabilityReadStatus", availabilityReadStatus)
        .put("statusReadStatus", statusReadStatus)
}

internal object VisionAssistProbe {
    private const val SNAPSHOT_TIMEOUT_MS = 900L

    fun snapshot(): VisionAssistSnapshot {
        val manager = MediaDataCenter.getInstance().cameraStreamManager
        val latch = CountDownLatch(6)

        val cameras = AtomicReference<List<ComponentIndexType>>(emptyList())
        val availableReceived = AtomicBoolean(false)
        val streamEnabled = AtomicReference<Boolean?>(null)
        val streamMapReceived = AtomicBoolean(false)
        val enabled = AtomicReference<Boolean?>(null)
        val enabledReceived = AtomicBoolean(false)
        val direction = AtomicReference<VisionAssistDirection?>(null)
        val directionReceived = AtomicBoolean(false)
        val range = AtomicReference<List<VisionAssistDirection>>(emptyList())
        val rangeReceived = AtomicBoolean(false)
        val motorsOn = AtomicReference<Boolean?>(null)
        val motorsReceived = AtomicBoolean(false)

        val cameraListener = object : ICameraStreamManager.AvailableCameraUpdatedListener {
            override fun onAvailableCameraUpdated(
                availableCameraList: MutableList<ComponentIndexType>
            ) {
                cameras.set(availableCameraList.toList())
                availableReceived.set(true)
                latch.countDown()
            }

            override fun onCameraStreamEnableUpdate(
                map: MutableMap<ComponentIndexType, Boolean>
            ) {
                streamEnabled.set(map[ComponentIndexType.VISION_ASSIST])
                streamMapReceived.set(true)
                latch.countDown()
            }
        }

        val visionListener = object : ICameraStreamManager.VisionAssistStatusListener {
            override fun onVisionAssistEnabled(isEnable: Boolean) {
                enabled.set(isEnable)
                enabledReceived.set(true)
                latch.countDown()
            }

            override fun onVisionAssistViewDirectionUpdated(mode: VisionAssistDirection) {
                direction.set(mode)
                directionReceived.set(true)
                latch.countDown()
            }

            override fun onVisionAssistViewDirectionRangeUpdated(
                modes: MutableList<VisionAssistDirection>
            ) {
                range.set(modes.toList())
                rangeReceived.set(true)
                latch.countDown()
            }
        }

        manager.addAvailableCameraUpdatedListener(cameraListener)
        manager.addVisionAssistStatusListener(visionListener)
        KeyManager.getInstance().getValue(
            KeyTools.createKey(FlightControllerKey.KeyAreMotorsOn),
            object : CommonCallbacks.CompletionCallbackWithParam<Boolean> {
                override fun onSuccess(value: Boolean?) {
                    motorsOn.set(value)
                    motorsReceived.set(true)
                    latch.countDown()
                }

                override fun onFailure(error: IDJIError) {
                    latch.countDown()
                }
            }
        )
        try {
            latch.await(SNAPSHOT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
        } finally {
            manager.removeAvailableCameraUpdatedListener(cameraListener)
            manager.removeVisionAssistStatusListener(visionListener)
        }

        val availableList = cameras.get()
        val visionStreamAvailable = if (availableReceived.get()) {
            ComponentIndexType.VISION_ASSIST in availableList
        } else {
            null
        }
        return VisionAssistSnapshot(
            available = visionStreamAvailable,
            streamAvailable = visionStreamAvailable,
            motorsOn = if (motorsReceived.get()) motorsOn.get() else null,
            availableCameraIndices = availableList.map { it.name },
            streamEnabled = if (streamMapReceived.get()) streamEnabled.get() else null,
            enabled = if (enabledReceived.get()) enabled.get() else null,
            direction = if (directionReceived.get()) direction.get()?.name else null,
            directionRange = if (rangeReceived.get()) range.get().map { it.name } else emptyList(),
            availabilityReadStatus =
                if (availableReceived.get()) "OK" else "UNAVAILABLE",
            statusReadStatus =
                if (enabledReceived.get() || directionReceived.get() || rangeReceived.get()) "OK"
                else "UNAVAILABLE"
        )
    }
}
