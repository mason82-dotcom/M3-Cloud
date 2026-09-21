# M3-Cloud Thermal Worker

Standalone x86-64 worker for radiometric DJI M3T R-JPEG processing.

The worker consumes the versioned M3-Cloud `THERMOGRAM` handoff, verifies the
frozen source file size/SHA256, decodes the catalogued M3T thermal R-JPEG
(including DJI `*_T.JPG` and `*_R.JPG` naming) with DJI's DIRP API, and
writes immutable processing artifacts into the job result-drop directory.

## Why it is separate from the backend

DJI Thermal SDK binaries are platform-specific. M3-Cloud deliberately does not
vendor them and does not load them inside the backend process. The worker can
therefore run on a Windows/Linux x86-64 workstation while the M3-Cloud backend
continues to run elsewhere.

The recommended runtime is DJI Thermal SDK 1.8. Point the worker at a locally
installed/extracted SDK with `DJI_TSDK_DIR`. The adapter also works with a
release directory containing `libdirp.dll` or `libdirp.so` directly.

If a supplied directory contains more than one x86-64 DJI TSDK release, the
worker rejects it and requires the exact release directory. This avoids
silently pairing one `libdirp` binary with another release's headers.

Review and comply with the DJI Thermal SDK license/EULA for the SDK version you
install. No DJI binary is committed to this repository.

## M3T-only source identity

The native workflow is intentionally scoped to DJI **Mavic 3 Thermal (M3T)**.
M3-Cloud recognizes both the `_T` thermal suffix used by current datasets and
the `_R` radiometric-JPEG suffix present in the reviewed M3T reference files.
The latter is distinct from M3M's `_MS_R.TIF` red spectral band and is
classified only as M3T `THERMAL`.
Before decoding each frozen WIDE/THERMAL pair, the worker inspects the
already-catalogued camera-model metadata from M3-Cloud:

- common M3T aliases such as `M3T`, `Mavic 3T` and
  `Mavic 3 Thermal` produce `CONFIRMED`;
- known different DJI platforms such as M3E, M3M, M3TD, M30T, H30T or M4T
  produce `CONFLICT` and the job fails before DIRP decode;
- missing or unrecognized model strings produce `UNCONFIRMED`, not a guessed
  identity.

Unknown sensor-specific codes therefore remain processable while a clearly
misclassified non-M3T dataset cannot silently pass through the M3T-only
pipeline. The evidence is preserved per capture and in the job manifest.

## Output contract

For each complete M3T WIDE/THERMAL capture pair the worker writes:

- `temperature.tif` — Float32 temperature plane in degrees Celsius.
- `preview.png` — 8-bit percentile-stretched preview for display only.
- `hotspot-mask.png` — binary sensor-space mask of generic hot-region candidates.
- `hotspots.json` — median-ΔT candidate components and sensor-pixel coordinates.
- `thermal.json` — source hashes, DIRP/R-JPEG provenance, dimensions,
  measurement-parameter mode, SDK ranges, temperature statistics and hotspot analysis.
- `capture-points.geojson` — source-image GPS capture centers with per-capture
  temperature/hotspot summaries; no pixel georeferencing is implied.
- `registration-audit.json` — WIDE/THERMAL pair evidence (capture-time,
  GPS, gimbal and raw DJI calibration hints) with status fixed to
  `NOT_REGISTERED`; it contains no pixel transform.
- `thermal-summary.json` — job-level aggregate plus one summary record per capture.
- `thermal-summary.csv` — tabular export of the same per-capture summary fields.
- `result-manifest.json` — job-level `M3T_THERMAL_RESULTS_V1` manifest.

The temperature TIFF is intentionally **not** labelled as a GeoTIFF. It remains
in thermal-sensor pixel space. `capture-points.geojson` contains only the
source image position (`CAPTURE_CENTER_ONLY`). WIDE/THERMAL coregistration and
pixel-level map georeferencing are separate processing stages.

`registration-audit.json` is deliberately an **evidence artifact**, not a
registration result. For every frozen WIDE/THERMAL pair it records the evidence
that is actually present: capture-time delta, GPS separation, gimbal and flight
attitude deltas, DJI/GPS altitude deltas, image dimensions/focal-length
metadata, and raw DJI calibration hints. Job-level `evidence_counts` report how
many pairs contain each evidence class.

Those counts are presence/completeness facts only. They are not a quality score,
do not imply that two images are optically aligned, and never change
`status: NOT_REGISTERED`. A later registration stage must provide a separately
validated camera-model-specific intrinsic/extrinsic transform before any thermal
pixel or hotspot can be projected into WIDE imagery or map coordinates.

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

DIRP's `dirp_get_api_version` call changed ABI across SDK generations. Older
headers such as TSDK 1.4 expose the global
`dirp_get_api_version(version)` form, while TSDK 1.5/1.8 headers expose
`dirp_get_api_version(handle, version)`. The worker detects that call shape
from the installed `dirp_api.h` and binds the matching ctypes signature.
If only a bare `libdirp` binary is supplied with no confirming header, the
worker still decodes the R-JPEG but skips this provenance-only API-version
query rather than guessing an unsafe C function arity. The result is marked
with `API_VERSION_ABI_UNCONFIRMED`.

For every run, the worker records the actual loaded DIRP library filename and
SHA-256 digest in the per-capture metadata, TIFF description, job manifest and
summary. All captures in one job must report the same decoder provenance;
otherwise processing fails closed. The configured `DJI_TSDK_VERSION` label is
therefore descriptive only—the binary hash is the authoritative decoder
identity.



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

The root `compose.yaml` exposes the worker only through the optional
`thermal` profile. After setting `DJI_TSDK_HOST_PATH` and the shared media
paths in `.env`, start the normal stack plus the worker with:

```bash
docker compose --profile thermal up -d
```

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

For the integrated M3-Cloud stack, place/extract the **Linux x86-64** DJI
Thermal SDK at `DJI_TSDK_HOST_PATH` and start the optional Compose profile:

```bash
docker compose --profile thermal up -d thermal-worker
```

The worker then uses `http://backend:8000`, claims eligible M3T jobs
atomically, processes them in FIFO order, publishes into the shared
`processing-import` mount, and asks M3-Cloud to import the results. The normal
stack does not start this service unless the `thermal` profile is enabled.

Do not point the container profile at the Windows DJI SDK package. Run the
Python worker natively on Windows for DLL-based processing, or install the
Linux x86-64 TSDK for the container.

## Safety / data integrity

- Source files are re-hashed before decode; changed frozen inputs fail closed.
- DIRP return codes raise typed exceptions; Python `assert` is not used for
  SDK correctness.
- The SDK-reported R-JPEG width/height are authoritative.
- The R-JPEG buffer remains alive until the DIRP handle is destroyed.
- DIRP handles are destroyed in `finally`.
- Temperature products preserve the source SHA256, SDK/R-JPEG provenance and
  the exact loaded `libdirp` SHA-256 identity.
- Job summaries and capture-center GeoJSON are derived only from frozen inputs and
  are covered by the same immutable processing fingerprint.
- No RGB/thermal pixel alignment is assumed; capture GPS never promotes a sensor-space
  temperature plane or hotspot mask to a georeferenced raster.
