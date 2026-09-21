# thermal_parser compatibility review

Reference reviewed: `SanNianYiSi/thermal_parser` at
`b513647ef2318ba99dd2e2a543fa0fb071fd9579`.

This document records source-derived compatibility findings used to shape the
M3-Cloud M3T thermal worker. It is not a claim that the external project is
incorrect for all of its supported cameras; the comparison below is scoped to
the M3T/modern DJI DIRP path that M3-Cloud uses.

## Confirmed M3T reference characteristics

The external repository includes five M3T R-JPEG examples. Their ExifTool
sidecars identify:

- camera/drone model `M3T`;
- thermal image size `640x512`;
- physical focal length `9.1 mm`, 35 mm equivalent `40 mm`;
- reported field of view `48.5 deg`;
- DJI `UTCAtExposure` timestamps with microsecond precision;
- GPS, absolute/relative altitude, flight attitude and gimbal attitude;
- `Has Settings: False` on the reviewed M3T examples;
- a 655360-byte thermal-data block, equal to `640 * 512 * 2` bytes.

These values are useful validation references, but M3-Cloud does not hard-code
the sample resolution or metadata values as a decoder truth source. DIRP remains
authoritative for decoded dimensions, and frozen source metadata is used as an
independent consistency check.

## DIRP path confirmed by thermal_parser

For modern DJI cameras, including M3T, `thermal_parser` ultimately decodes the
R-JPEG through DJI DIRP and `dirp_measure_ex()` to obtain a Float32 Celsius
plane. This matches the core M3-Cloud decoder strategy.

The project currently defaults to DJI Thermal SDK
`dji_thermal_sdk_v1.7_20241205`.

## Important implementation differences

### Resolution handling

`thermal_parser.parse_dirp2()` calls `dirp_get_rjpeg_resolution()`, but its
output buffer allocation/reshape uses supplied/default `image_width` and
`image_height` values instead of the returned DIRP dimensions.

M3-Cloud uses the DIRP-reported width/height as authoritative and additionally
cross-checks those dimensions against the frozen source metadata. A mismatch is
reported as `SOURCE_DIMENSION_MISMATCH`.

### Measurement parameters

`thermal_parser` marks M3T as `m2ea_mode=True`; this skips
`dirp_get_measurement_params()` and `dirp_set_measurement_params()` entirely.

M3-Cloud instead probes the SDK:

- supported/readable parameters are preserved as provenance;
- unsupported/not-ready parameters become `sdk_native_locked`;
- unreadable parameters become `sdk_native_unreadable`;
- user-requested overrides fail closed if DIRP cannot read/set them;
- when available, `dirp_get_measurement_params_range()` is authoritative for
  override validation.

### Modern measurement ABI

The reviewed `thermal_parser` Python structure contains four floats:
`distance`, `humidity`, `emissivity`, and `reflection`.

Modern DJI headers (including TSDK 1.5+ examples and the reviewed 1.8 header)
contain a fifth field, `ambient_temp`, and the corresponding range structure
also contains `ambient_temp`.

M3-Cloud detects this header ABI and uses the five-field structure for modern
SDKs. It does not infer an ambient-temperature override when the ABI is
unconfirmed.

### dirp_get_api_version ABI change

DJI changed the call shape across SDK generations:

- older headers such as TSDK 1.4:
  `dirp_get_api_version(version)`;
- newer headers such as TSDK 1.5/1.8:
  `dirp_get_api_version(handle, version)`.

M3-Cloud detects the declaration in the installed `dirp_api.h` and binds the
matching ctypes signature. When the header is absent, it skips this
provenance-only query instead of guessing the C function arity and marks
`API_VERSION_ABI_UNCONFIRMED`.

### Handle lifetime and error handling

The external implementation relies heavily on Python `assert` statements and
destroys the DIRP handle only on the normal successful path.

M3-Cloud raises typed exceptions for DIRP failures and destroys every created
handle in `finally`, so decode/measurement failures do not leave the normal
cleanup path.

### SDK packaging

The external repository includes DJI SDK binaries for several versions.

M3-Cloud deliberately keeps DJI native libraries outside the repository. The
worker loads a locally supplied SDK directory on Windows/Linux x86-64. This
keeps the backend independent from platform-specific thermal binaries and
avoids coupling the repository to one bundled SDK release.

## Metadata finding adopted by M3-Cloud

The M3T reference files expose DJI XMP `UTCAtExposure` with microsecond
precision. This is a stronger flight-association timestamp than an ambiguous
local EXIF `DateTimeOriginal`.

M3-Cloud metadata schema version 2 therefore prefers:

1. DJI XMP `UTCAtExposure` as UTC;
2. EXIF original time/offset;
3. generic XMP `CreateDate`;
4. filename-derived fallback.

Existing catalog entries are re-extracted automatically on the next scan
because the metadata schema version was incremented.

## Registration boundary

The reviewed M3T metadata contains GPS, gimbal/flight attitude and DJI camera
calibration fields, but neither `thermal_parser` nor the current M3-Cloud
worker establishes a proven WIDE-to-THERMAL pixel transform from those values
alone.

The reference M3T sidecars also show why the DJI calibration strings must not be
silently assigned units: EXIF reports `Focal Length = 9.1 mm`, while DJI XMP
reports `Calibrated Focal Length = 9100.000000` and the reviewed thermal
examples report `Calibrated Optical Center X/Y = 0.000000`. The source does
not define the XMP calibration units or prove that those three values alone form
a usable thermal-camera intrinsic model. M3-Cloud therefore preserves them as
raw DJI calibration evidence and does not convert them to millimetres, pixels,
or a camera matrix.

M3-Cloud therefore keeps:

- temperature TIFFs and hotspot masks in thermal sensor-pixel space;
- source-image GPS only as `CAPTURE_CENTER_ONLY` GeoJSON points;
- `wide_thermal_coregistered=false`;
- `georeferenced_temperature_raster=false`.

A future registration stage must define and validate the camera-model-specific
intrinsic/extrinsic transform before any thermal pixel or hotspot is placed on
the map.
