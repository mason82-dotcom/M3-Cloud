# Matrice 4T + DJI RC Plus 2 Enterprise

M3-Cloud treats Matrice 4T as a first-class platform, separate from M3T.

## Runtime baseline

- Android application: DJI MSDK 5.18.0 (already pinned by Lyrebird).
- Controller target: DJI RC Plus 2 Enterprise.
- Aircraft camera discriminator: MSDK `CameraType.M4T`.
- Visual capture source: `WIDE_CAMERA`.
- Radiometric capture source: `INFRARED_CAMERA`.
- Thermal decoding: DJI Thermal SDK / DIRP supplied outside the repository.
- Thermogram handoff contract: `M4T_RJPEG_V1`.
- Result contract: `M4T_THERMAL_RESULTS_V1`.

M4T is never treated as an alias of M3T. Camera capability, media identity and
thermal result provenance retain the M4T platform name end to end.

## Media layout

Put synchronized camera originals below an M4T-qualified import prefix, for
example:

```text
media-import/
  M4T/
    2026-09-21-inspection/
      DJI_..._W.JPG
      DJI_..._R.JPG
```

Radiometric `_T.JPG` and `_R.JPG` names are accepted for integrated M3T/M4T
thermal cameras. M3M `_MS_R.TIF` remains a multispectral red-band file and is
never classified as thermal.

A thermal capture can be processed without a Wide companion. If Wide is
present, M3-Cloud records pair evidence but does not claim pixel registration.

## Capture policy

The initial field-safe profiles are deliberately separate:

- `M4T_WIDE`: stores `WIDE_CAMERA`.
- `M4T_THERMAL`: stores `INFRARED_CAMERA`.

Lyrebird verifies the requested storage source through
`KeyCaptureCameraStreamSettings` readback before triggering the shutter.
A combined Wide + infrared storage profile should only become a default after
that exact combination has been verified on the target M4T/RC Plus 2 firmware.

## Thermal products

The x86-64 thermal worker keeps the DIRP-reported image dimensions authoritative.
This accommodates the M4T thermal sensor's native and super-resolution R-JPEG
products without hard-coding a 640x512 processing raster.

Outputs remain the same logical products as M3T:

- Float32 Celsius temperature TIFF in sensor-pixel coordinates.
- display preview.
- generic hotspot-candidate mask and JSON.
- radiometry/decoder provenance.
- capture-center GeoJSON.
- WIDE/THERMAL registration audit with status `NOT_REGISTERED`.
- immutable result manifest and summaries.

## Field validation still required

Before production flight use, validate on the exact aircraft/controller firmware:

1. `CameraType.M4T` readback.
2. reported stream-source range.
3. `M4T_WIDE` set/readback/shutter.
4. `M4T_THERMAL` set/readback/shutter and actual R-JPEG filename.
5. original-file download and SHA-256 preservation.
6. DIRP decode of both 640x512 and, when enabled, 1280x1024 thermal photos.
7. thermal gain/FFC state capture.
8. RTK, gimbal, aircraft attitude and DJI XMP metadata extraction.
9. RC Plus 2 -> M3-Cloud media synchronization.

The existing HTTP endpoints remain useful for field validation:
`/send/captureThermalImage`, `/send/listMedia`, and
`/send/downloadMediaByName`.
