---
title: Enterprise Camera Platforms
description: MSDK 5.18 camera identity, capture profiles, and the strict separation between M3E, M3T, and M3M.
breadcrumb: Interfaces
---

Lyrebird treats **M3E, M3T, and M3M as different camera platforms**, even though DJI groups part of
the hardware family under a common Mavic 3 Enterprise product line. The discriminator used for
capture behavior is the MSDK camera type, not a shared product-family label and not a filename
suffix.

This matters because the three platforms have different stored sources and different payload
capabilities:

| Platform | Lyrebird platform | Default direct-photo profile | Default DJI-native survey profile | Thermal | Multispectral |
|---|---|---|---|---|---|
| Mavic 3 Enterprise | `M3E` | `M3E_MAPPING` | `M3E_MAPPING` | no | no |
| Mavic 3 Thermal | `M3T` / `M3TA` | `M3T_WIDE` | `M3T_WIDE` | yes | no |
| Mavic 3 Multispectral | `M3M` | `M3M_RGB` | `M3M_RGB_MULTISPECTRAL` | no | yes |

Unknown/new camera types fail closed as `OTHER`; they do not inherit M3E/M3T/M3M behavior by
similarity.

## Capture profiles

The active capture profile controls **stored photo sources**, not the live-view source:

| Profile | Stored sources requested from MSDK |
|---|---|
| `M3E_MAPPING` | `WIDE_CAMERA` |
| `M3T_WIDE` | `WIDE_CAMERA` |
| `M3T_THERMAL` | `INFRARED_CAMERA` |
| `M3M_RGB` | `RGB_CAMERA` |
| `M3M_RGB_MULTISPECTRAL` | `RGB_CAMERA`, `NDVI_CAMERA`, `MS_G_CAMERA`, `MS_R_CAMERA`, `MS_RE_CAMERA`, `MS_NIR_CAMERA` |

For the M3M, the multispectral survey profile intentionally retains all six MSDK stored-source
identities. `NDVI_CAMERA` is a stored stream identity, not an assertion that the aircraft has a
fifth physical multispectral sensor.

The current M3T policy exposes wide and thermal profiles. It does **not** currently expose a
separate 48 MP/high-resolution survey profile, so mission planning must not assume that
`M3T_WIDE` means a verified 48 MP capture mode.

## Prepare, set, read back

For M3-family cameras, a photo is not triggered until the camera configuration has been prepared
and verified:

```
CameraType
   ↓
platform/profile match
   ↓
KeyCameraVideoStreamSourceRange contains every requested stored source
   ↓
set PHOTO_NORMAL
   ↓
set KeyCaptureCameraStreamSettings
   ↓
fresh MSDK readback
   ↓
requested sources == readback sources
   ↓
trigger shutter
```

If the platform does not match the requested profile, a required source is absent from the runtime
source range, or the readback differs from the request, preparation fails instead of silently
falling back to another lens.

Changing camera mode can alter the operator's current live-view source on some hardware. Lyrebird
therefore records the current live source before photo preparation and tries to restore it after the
stored-source configuration has been verified. Live view and capture storage remain separate state.

## Direct capture and multi-asset exposures

One shutter is not assumed to equal one file. `Payload.captureExposure()` returns the complete set
of `MediaFile` objects produced by the shutter together with the detected camera type/platform.
This is required for M3M RGB+multispectral capture, where one exposure can produce several assets.

The legacy `capturePhoto()` API remains for callers that need one representative image; it selects
a primary image from the exposure. New code that cares about multispectral completeness should use
the full exposure instead.

Thermal capture is capability-gated. M3E and M3M are rejected as non-thermal platforms rather than
trying to infer a thermal file from file size or filename shape. The M3T has an explicit thermal
profile; legacy H20T/H20N/H30T payloads retain their legacy hybrid path.

## Read-only capability endpoint

The HTTP endpoint:

```text
GET /get/camera/capabilities
```

performs a read-only MSDK characterization. It does not change camera mode or storage configuration.
The response includes:

- `cameraType`, `platform`, camera firmware and connection state;
- current camera mode and the reported mode range;
- current live-view source and source range;
- stored capture/record sources when the corresponding mode permits a fresh read;
- `thermalCapture` and `multispectralCapture` capability flags;
- the current Vision Assist probe result.

The capture/record stored-source reads are intentionally reported with a status such as
`OK`, `UNAVAILABLE`, or `NOT_APPLICABLE` instead of fabricating an empty, valid-looking
configuration when MSDK cannot read the key in the current mode.

## Native survey behavior

Before a DJI-native mission containing `DO_SET_CAM_TRIGG_DIST` is launched, Lyrebird selects the
platform's **default survey profile** and runs the same prepare/readback sequence. For the three
M3-family platforms this means:

```text
M3E → M3E_MAPPING
M3T → M3T_WIDE
M3M → M3M_RGB_MULTISPECTRAL
```

A profile/readback failure aborts mission launch before take-off. Distance-triggered shutter actions
still target DJI payload position `0`; lens/source selection belongs to the verified capture
profile and is not encoded by repurposing MAVLink `DO_SET_CAM_TRIGG_DIST.param4`.

See [Missions](/missions/) for the distance-trigger compiler and [HTTP API](/http-api/) for the
diagnostic endpoint.
