# M3-Cloud Thermal Worker

Standalone x86-64 worker for radiometric DJI M3T R-JPEG processing.

The worker consumes the versioned M3-Cloud `THERMOGRAM` handoff, verifies the
frozen source file size/SHA256, decodes the `*_T.JPG` with DJI's DIRP API, and
writes immutable processing artifacts into the job result-drop directory.

## Why it is separate from the backend

DJI Thermal SDK binaries are platform-specific. M3-Cloud deliberately does not
vendor them and does not load them inside the backend process. The worker can
therefore run on a Windows/Linux x86-64 workstation while the M3-Cloud backend
continues to run elsewhere.

The recommended runtime is DJI Thermal SDK 1.8. Point the worker at a locally
installed/extracted SDK with `DJI_TSDK_DIR`. The adapter also works with a
release directory containing `libdirp.dll` or `libdirp.so` directly.

Review and comply with the DJI Thermal SDK license/EULA for the SDK version you
install. No DJI binary is committed to this repository.

## Output contract

For each complete M3T WIDE/THERMAL capture pair the worker writes:

- `temperature.tif` — Float32 temperature plane in degrees Celsius.
- `preview.png` — 8-bit percentile-stretched preview for display only.
- `hotspot-mask.png` — binary sensor-space mask of generic hot-region candidates.
- `hotspots.json` — median-ΔT candidate components and sensor-pixel coordinates.
- `thermal.json` — source hashes, DIRP/R-JPEG provenance, dimensions,
  measurement-parameter mode, SDK ranges, temperature statistics and hotspot analysis.
- `result-manifest.json` — job-level `M3T_THERMAL_RESULTS_V1` manifest.

The temperature TIFF is intentionally **not** labelled as a GeoTIFF. It remains
in thermal-sensor pixel space. WIDE/THERMAL coregistration and map
georeferencing are separate processing stages.

## Install

```bash
cd thermal-worker
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
export DJI_TSDK_DIR=/opt/dji-tsdk
export DJI_TSDK_VERSION=1.8_20251211
```

Windows PowerShell:

```powershell
cd thermal-worker
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
$env:DJI_TSDK_DIR = "C:\DJI\Thermal-SDK"
$env:DJI_TSDK_VERSION = "1.8_20251211"
```

## Run

Download the handoff JSON from M3-Cloud and run:

```bash
m3-thermal-worker m3t-thermogram-handoff.json
```

The default output path is `result_drop_path` from the handoff. Override it
when testing locally:

```bash
m3-thermal-worker m3t-thermogram-handoff.json \
  --result-dir ./thermal-results
```

Optional measurement overrides are accepted only inside DJI DIRP's documented
ranges:

```bash
m3-thermal-worker m3t-thermogram-handoff.json \
  --emissivity 0.95 \
  --distance-m 10 \
  --humidity-pct 65 \
  --reflection-c 20 \
  --ambient-temp-c 20
```

Some DJI radiometric products expose their measurement parameters as
non-editable through DIRP. With no overrides, the worker records
`measurement_mode=sdk_native_locked` and uses the SDK-native radiometry.
If an override is explicitly requested but DIRP cannot read/set the
measurement parameters, the job fails closed rather than claiming that the
override was applied. When available, the worker queries
`dirp_get_measurement_params_range()` and validates overrides against the
camera/R-JPEG-specific DJI ranges rather than relying on a hard-coded distance limit.

The adapter targets the modern DIRP measurement ABI used by current TSDK,
including the `ambient_temp` field present in the current header layout.



Generic hotspot candidate analysis defaults to a threshold of 10 °C above the
image median with a minimum 4-connected component size of four thermal pixels.
It is deliberately **not** a PV/equipment defect classifier. Adjust it with:

```bash
m3-thermal-worker m3t-thermogram-handoff.json \
  --hotspot-delta-c 8 \
  --hotspot-min-pixels 6
```

The analysis settings and radiometric overrides are included in the immutable
input fingerprint. A retry only reuses an existing result folder when the
frozen source set **and** processing settings match.


For automatic job-state callbacks and result import:

```bash
m3-thermal-worker m3t-thermogram-handoff.json \
  --api-base http://m3-cloud:8000 \
  --import-results
```

This transitions the existing M3-Cloud external processing job through
`RUNNING_EXTERNAL` and `COMPLETED_EXTERNAL`, then invokes the existing
result import endpoint.

## Docker

The image does not contain DJI's SDK. Mount your SDK and the two shared
handoff/result paths explicitly. Example:

```bash
docker build -t m3-thermal-worker ./thermal-worker

docker run --rm \
  -v /opt/dji-tsdk:/opt/dji-tsdk:ro \
  -v /srv/m3/media-import:/media-import:ro \
  -v /srv/m3/processing-import:/processing-import \
  -v "$PWD/m3t-thermogram-handoff.json:/work/handoff.json:ro" \
  m3-thermal-worker /work/handoff.json
```

The paths encoded in `external_path` and `result_drop_path` must be visible
inside the worker under the same names, or use `--result-dir` and a locally
prepared handoff path mapping.

## Safety / data integrity

- Source files are re-hashed before decode; changed frozen inputs fail closed.
- DIRP return codes raise typed exceptions; Python `assert` is not used for
  SDK correctness.
- The SDK-reported R-JPEG width/height are authoritative.
- The R-JPEG buffer remains alive until the DIRP handle is destroyed.
- DIRP handles are destroyed in `finally`.
- Temperature products preserve the source SHA256 and SDK/R-JPEG provenance.
- No RGB/thermal pixel alignment is assumed.
