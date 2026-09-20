package com.lyrebird.rc.controller

import android.os.Handler
import android.os.Looper
import dji.sdk.keyvalue.key.CameraKey
import dji.sdk.keyvalue.key.DJIKey
import dji.sdk.keyvalue.key.KeyTools
import dji.sdk.keyvalue.value.camera.CameraMode
import dji.sdk.keyvalue.value.camera.CameraStreamSettingsInfo
import dji.sdk.keyvalue.value.camera.CameraType
import dji.sdk.keyvalue.value.camera.CameraVideoStreamSourceType
import dji.sdk.keyvalue.value.common.ComponentIndexType
import dji.v5.common.callback.CommonCallbacks
import dji.v5.common.error.IDJIError
import dji.v5.et.get
import dji.v5.et.set
import dji.v5.manager.KeyManager

internal data class CameraPrepareResult(
    val success: Boolean,
    val profile: CameraCaptureProfile?,
    val detail: String
)

internal object CameraCaptureConfigurator {
    private const val LIVE_SOURCE_ATTEMPTS = 2
    private const val LIVE_SOURCE_RETRY_DELAY_MS = 200L

    fun defaultDirectProfile(capabilities: CameraPlatformCapabilities): CameraCaptureProfile? =
        CameraCapturePolicy.defaultDirectProfile(capabilities)

    fun defaultSurveyProfile(capabilities: CameraPlatformCapabilities): CameraCaptureProfile? =
        CameraCapturePolicy.defaultSurveyProfile(capabilities)

    fun thermalProfile(capabilities: CameraPlatformCapabilities): CameraCaptureProfile? =
        CameraCapturePolicy.thermalProfile(capabilities)

    /**
     * Prepare PHOTO_NORMAL and its stored lens sources, then verify the capture-source readback.
     *
     * This method is asynchronous on purpose. MSDK action/key callbacks must not be turned into a
     * main-thread blocking wait. Callers that already run a worker can wait on their own latch.
     */
    fun preparePhoto(
        profile: CameraCaptureProfile,
        index: ComponentIndexType = ComponentIndexType.LEFT_OR_MAIN,
        callback: (CameraPrepareResult) -> Unit
    ) {
        val typeKey: DJIKey<CameraType> = KeyTools.createKey(CameraKey.KeyCameraType, index)
        val cameraType = typeKey.get(CameraType.NOT_SUPPORTED)
        val capabilities =
            CameraPlatformCapabilities.fromCameraTypeName(cameraType?.name)

        if (capabilities.platform != profile.platform) {
            callback(
                CameraPrepareResult(
                    false,
                    profile,
                    "Profile ${profile.name} does not match camera ${cameraType?.name ?: "UNKNOWN"}"
                )
            )
            return
        }

        val sourceRangeKey: DJIKey<List<CameraVideoStreamSourceType>> =
            KeyTools.createKey(CameraKey.KeyCameraVideoStreamSourceRange, index)
        val supportedSources = sourceRangeKey.get(emptyList())
        val supportedByName = supportedSources.associateBy { it.name }
        val missing = profile.storedSourceNames.filterNot(supportedByName::containsKey)
        if (missing.isNotEmpty()) {
            callback(
                CameraPrepareResult(
                    false,
                    profile,
                    "Camera does not report capture source(s): ${missing.joinToString()}"
                )
            )
            return
        }
        val requestedSources = profile.storedSourceNames.mapNotNull(supportedByName::get)

        val modeKey: DJIKey<CameraMode> = KeyTools.createKey(CameraKey.KeyCameraMode, index)
        val captureKey: DJIKey<CameraStreamSettingsInfo> =
            KeyTools.createKey(CameraKey.KeyCaptureCameraStreamSettings, index)
        val liveSourceKey: DJIKey<CameraVideoStreamSourceType> =
            KeyTools.createKey(CameraKey.KeyCameraVideoStreamSource, index)

        fun restoreLiveSourceThenComplete(
            previousSource: CameraVideoStreamSourceType?,
            detail: String
        ) {
            if (previousSource == null) {
                callback(CameraPrepareResult(true, profile, detail))
                return
            }

            fun attemptRestore(attemptsRemaining: Int) {
                KeyManager.getInstance().setValue(
                    liveSourceKey,
                    previousSource,
                    object : CommonCallbacks.CompletionCallback {
                        override fun onSuccess() {
                            KeyManager.getInstance().getValue(
                                liveSourceKey,
                                object : CommonCallbacks.CompletionCallbackWithParam<CameraVideoStreamSourceType> {
                                    override fun onSuccess(readback: CameraVideoStreamSourceType?) {
                                        val suffix = if (readback == previousSource) {
                                            "; liveSource=${previousSource.name}"
                                        } else {
                                            "; liveSource restore mismatch: expected=${previousSource.name} actual=${readback?.name}"
                                        }
                                        callback(CameraPrepareResult(true, profile, detail + suffix))
                                    }

                                    override fun onFailure(error: IDJIError) {
                                        callback(
                                            CameraPrepareResult(
                                                true,
                                                profile,
                                                "$detail; liveSource restore readback failed: ${error.description()}"
                                            )
                                        )
                                    }
                                }
                            )
                        }

                        override fun onFailure(error: IDJIError) {
                            if (attemptsRemaining > 1) {
                                Handler(Looper.getMainLooper()).postDelayed(
                                    { attemptRestore(attemptsRemaining - 1) },
                                    LIVE_SOURCE_RETRY_DELAY_MS
                                )
                            } else {
                                callback(
                                    CameraPrepareResult(
                                        true,
                                        profile,
                                        "$detail; liveSource restore failed: ${error.description()}"
                                    )
                                )
                            }
                        }
                    }
                )
            }

            attemptRestore(LIVE_SOURCE_ATTEMPTS)
        }

        fun configurePhoto(previousSource: CameraVideoStreamSourceType?) {
            modeKey.set(
                CameraMode.PHOTO_NORMAL,
                onSuccess = {
                    val settings = CameraStreamSettingsInfo()
                        .setRequestCurrentScreen(false)
                        .setCameraVideoStreamSources(ArrayList(requestedSources))
                    captureKey.set(
                        settings,
                        onSuccess = {
                            // Verify against a fresh MSDK read, not the synchronous key cache.
                            KeyManager.getInstance().getValue(
                                captureKey,
                                object : CommonCallbacks.CompletionCallbackWithParam<CameraStreamSettingsInfo> {
                                    override fun onSuccess(readback: CameraStreamSettingsInfo?) {
                                        val expected = profile.storedSourceNames.toSet()
                                        val actual = readback?.cameraVideoStreamSources
                                            .orEmpty()
                                            .map { it.name }
                                            .toSet()
                                        if (actual == expected) {
                                            restoreLiveSourceThenComplete(
                                                previousSource,
                                                "PHOTO_NORMAL; sources=${expected.sorted()}"
                                            )
                                        } else {
                                            callback(
                                                CameraPrepareResult(
                                                    false,
                                                    profile,
                                                    "Capture source readback mismatch: expected=$expected actual=$actual"
                                                )
                                            )
                                        }
                                    }

                                    override fun onFailure(error: IDJIError) {
                                        callback(
                                            CameraPrepareResult(
                                                false,
                                                profile,
                                                "Capture-stream readback failed: ${error.description()}"
                                            )
                                        )
                                    }
                                }
                            )
                        },
                        onFailure = { error ->
                            callback(
                                CameraPrepareResult(
                                    false,
                                    profile,
                                    "Capture-stream setting failed: ${error.description()}"
                                )
                            )
                        }
                    )
                },
                onFailure = { error ->
                    callback(
                        CameraPrepareResult(
                            false,
                            profile,
                            "PHOTO_NORMAL failed: ${error.description()}"
                        )
                    )
                }
            )
        }

        // Read the operator-selected source before changing camera mode. M3M field testing shows
        // VIDEO_NORMAL -> PHOTO_NORMAL resets the live source to RGB_CAMERA; restoring the prior
        // source after photo configuration preserves NDVI/G/R/RE/NIR selection without changing
        // which sources are actually written to storage.
        fun readLiveSourceBeforeCapture(attemptsRemaining: Int) {
            KeyManager.getInstance().getValue(
                liveSourceKey,
                object : CommonCallbacks.CompletionCallbackWithParam<CameraVideoStreamSourceType> {
                    override fun onSuccess(source: CameraVideoStreamSourceType?) {
                        configurePhoto(source)
                    }

                    override fun onFailure(error: IDJIError) {
                        if (attemptsRemaining > 1) {
                            Handler(Looper.getMainLooper()).postDelayed(
                                { readLiveSourceBeforeCapture(attemptsRemaining - 1) },
                                LIVE_SOURCE_RETRY_DELAY_MS
                            )
                        } else {
                            // Live-source preservation is secondary to capture preparation.
                            configurePhoto(null)
                        }
                    }
                }
            )
        }

        readLiveSourceBeforeCapture(LIVE_SOURCE_ATTEMPTS)
    }

}