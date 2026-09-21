# M3-Cloud

Self-hosted platform for DJI Enterprise aircraft integration, mission operations, telemetry, media processing and mapping.

## Target aircraft
- DJI Mavic 3 Enterprise (M3E)
- DJI Mavic 3 Thermal (M3T)
- DJI Mavic 3 Multispectral (M3M)
- DJI RC Pro Enterprise
- RTK/GNSS workflows

## Architecture
- `backend/app/dji/`: DJI Cloud API integration
- `backend/app/vehicles/`: aircraft/data-source abstraction
- `backend/app/integrations/`: external processing/GIS integrations
- `frontend/`: M3-Cloud user interface
- `lyrebird/`: Lyrebird integration and extensions
- `emqx/`: MQTT broker configuration
- `nginx/`: reverse proxy configuration
- `postgres/`: database-related configuration
- `minio/`: object/media storage configuration
- `scripts/`: maintenance/deployment scripts

## Core stack

The first runnable M3-Cloud core consists of:

- FastAPI backend
- PostgreSQL + PostGIS
- Redis
- EMQX MQTT broker
- MinIO object storage

Create a local environment file and start the stack:

```bash
cp .env.example .env
docker compose up -d --build
```

Check the backend:

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

The readiness endpoint reports PostgreSQL, Redis, MinIO and EMQX independently.

> The default credentials in `.env.example` are development placeholders. Change them before exposing any service beyond a trusted LAN.

Lyrebird remains the aircraft-side integration layer; persistent project, survey, processing and operator services belong in M3-Cloud.


### Reproducible dependency locks

Backend direct dependency constraints live in `backend/requirements.in` and
`backend/requirements-dev.in`. Production images install
`backend/requirements.lock`; CI installs `backend/requirements-dev.lock`.
Both lockfiles pin the complete resolved dependency graph and include package
hashes.

The frontend commits `frontend/package-lock.json`. Docker and CI use
`npm ci` so transitive JavaScript dependencies are installed exactly as
recorded in the lockfile.

Refresh all dependency locks intentionally with Python 3.12 and Node.js 22:

```bash
bash scripts/update-lockfiles.sh
```

Review the resulting dependency changes and run CI before merging them.
`backend/requirements.txt` remains only as a backward-compatible
developer/test wrapper around the development lockfile.


## DJI Pilot 2 Cloud API bootstrap

M3-Cloud includes a dedicated DJI Pilot 2 Open Platform page at:

```text
http://<m3-cloud-host>:8080/pilot2/
```

The current bootstrap intentionally enables only DJI's primary `thing`/MQTT path. It verifies the
DJI Cloud API license, connects Pilot 2 to EMQX and sets the M3-Cloud workspace identity. Pilot 2
modules that depend on additional DJI HTTPS/WebSocket contracts remain disabled until those
contracts are implemented end-to-end.

See [docs/dji-pilot2.md](docs/dji-pilot2.md) for server variables and the exact Pilot 2 steps.

## Fleet dashboard

The first browser dashboard is served through the frontend reverse proxy:

```text
http://localhost:8080
```

It loads the DJI device registry through `/api/v1/devices`, bootstraps current aircraft
telemetry through `/api/v1/devices/{sn}/telemetry`, and then follows live Redis-backed
WebSocket updates from `/ws/live`.

The default map style is MapLibre's public demo style. Set `VITE_MAP_STYLE_URL` at frontend
build time when using a self-hosted or project-specific style.


### Map fallback

MapLibre remains the only map engine. The browser first loads `VITE_MAP_STYLE_URL` (or the
MapLibre demo style when unset). If the primary style fails before it is ready, M3-Cloud switches
to a simple raster fallback defined by `VITE_MAP_FALLBACK_TILE_URL`.

The public OpenStreetMap tile URL in `.env.example` is suitable for light development use only.
For production deployments configure a self-hosted or commercial tile endpoint.


## Flight history

M3-Cloud persists detected flights in PostgreSQL/PostGIS. OSD samples are written only while a
flight is active. Start detection uses DJI M3 `mode_code` together with altitude/speed
confirmation; landing requires three low-motion standby OSD samples.

```text
GET /api/v1/flights
GET /api/v1/flights?aircraft_sn=<SN>
GET /api/v1/flights/<UUID>
```

Flight detail includes takeoff/landing positions and a GeoJSON path when at least two valid
positions were recorded. RTK reporting remains a convergence statistic derived from DJI
`position_state`; it is not labelled FIX/FLOAT.


## External media import

DJI SD-card media can be copied to a host folder and mounted read-only into M3-Cloud.
The backend catalogs the originals in place; it does not rename, resize, move, or rewrite them.

Example host layout:

```text
/mnt/m3-media-import/
├── M3E/
│   └── project-a/
├── M3T/
│   └── inspection-a/
└── M3M/
    └── field-a/
```

Set the host path in `.env`:

```dotenv
M3CLOUD_MEDIA_IMPORT_ENABLED=true
M3CLOUD_MEDIA_IMPORT_HOST_PATH=/mnt/m3-media-import
M3CLOUD_MEDIA_IMPORT_SCAN_INTERVAL_SECONDS=15
M3CLOUD_MEDIA_IMPORT_MIN_AGE_SECONDS=5
```

Docker mounts that directory as `/media-import:ro`. The scanner waits for the minimum
file age and verifies size/mtime around SHA-256 hashing so files still being copied are not
registered prematurely.

Media endpoints:

```text
GET  /api/v1/media
GET  /api/v1/media/groups
GET  /api/v1/media/import/status
POST /api/v1/media/import/scan
```

M3M default groups such as `*_D.JPG`, `*_MS_G.TIF`, `*_MS_R.TIF`,
`*_MS_RE.TIF`, and `*_MS_NIR.TIF` are kept together. For M3E/M3T, using the
`M3E/`, `M3T/`, or `M3M/` top-level folder is recommended so platform identity is
explicit even when a filename alone is ambiguous.


## WebODM processing workflow

M3-Cloud can process imported M3E/M3T RGB imagery with an external WebODM instance.
The originals remain read-only in the media import folder and are streamed byte-for-byte
to WebODM when a job is started.

Configure WebODM in `.env`:

```dotenv
M3CLOUD_WEBODM_ENABLED=true
M3CLOUD_WEBODM_URL=http://webodm-host:8000

# Use either an existing JWT token...
M3CLOUD_WEBODM_TOKEN=

# ...or credentials used to obtain one.
M3CLOUD_WEBODM_USERNAME=
M3CLOUD_WEBODM_PASSWORD=

M3CLOUD_WEBODM_TIMEOUT_SECONDS=300
M3CLOUD_PROCESSING_POLL_INTERVAL_SECONDS=5
```

The Processing view discovers eligible RGB/Wide datasets directly from the media catalog.
A processing job freezes the selected media asset IDs before upload, so later watch-folder
changes do not silently change an already queued job.

Selected WebODM results are archived in the `m3-results` MinIO bucket. In addition to the
original result object, `orthophoto.mbtiles` is published as XYZ raster tiles under:

```text
webodm/<job-uuid>/orthophoto/tiles/<z>/<x>/<y>.<format>
```

M3-Cloud converts the MBTiles TMS Y coordinate to XYZ during publication and exposes:

```text
GET /api/v1/processing/jobs/<UUID>/map
GET /api/v1/processing/jobs/<UUID>/map/tiles/<z>/<x>/<y>
```

The React Processing view can open the published orthophoto directly on MapLibre. The original
`orthophoto.mbtiles` remains archived in MinIO and is not modified.


### Media dataset readiness and external handoff

The media catalog evaluates each imported folder as a workflow dataset. Duplicate and missing files
are excluded from readiness calculations.

```text
GET /api/v1/media/datasets
GET /api/v1/media/datasets/manifest?prefix=M3T/site-a
```

Workflow readiness is reported separately:

- `WEBODM`: at least two present, non-duplicate RGB/Wide originals.
- `THERMOGRAM`: M3T capture groups contain both Wide and Thermal originals.
- `MULTISPECTRAL`: M3M capture groups contain RGB plus Green, Red, Red Edge, and NIR.

The handoff manifest contains the original relative paths, SHA-256 values, capture groups, and
completeness status. It references `/media-import/<prefix>`; it does not copy, rename, resize,
or rewrite the source files. This is the intended path for desktop tools such as Thermogram that
need the original DJI folder contents.

WebODM remains fully server-driven. When any processing job is created, M3-Cloud freezes the
selected media ID together with its relative path, byte size, SHA-256, media kind, and capture
group in `processing_job_assets`. Before WebODM upload the current source file is hashed again;
a changed original aborts the job instead of silently processing different bytes. Thermogram
handoff manifests are generated from the same frozen snapshot.


### M3M multispectral processing

M3-Cloud exposes a dedicated `m3m-multispectral` WebODM profile. A job is offered only when the
dataset contains at least two complete M3M captures, each with RGB plus Green, Red, Red Edge, and
NIR originals. Incomplete capture groups are excluded from the immutable job snapshot.

The profile uploads all five channels together and sets:

```text
radiometric-calibration = camera
```

This follows ODM's supported Mavic 3 Multispectral workflow. The `camera+sun` mode is not enabled
by default because ODM currently documents it as experimental.


### M3T radiometric processing

M3-Cloud limits the thermal workflow to **DJI Mavic 3 Thermal (M3T)** datasets.
It detects complete WIDE + THERMAL capture pairs, including DJI thermal
`*_T.JPG` and radiometric `*_R.JPG` naming, freezes those exact `MediaAsset`
records in a persistent `THERMOGRAM` processing job, and keeps the source
folder read-only.

The preferred processing path is the separate x86-64 `thermal-worker/`. It
loads a locally supplied DJI Thermal SDK (the SDK binaries are not vendored in
this repository), verifies each frozen source by size/SHA-256, and decodes the
original thermal R-JPEG through DIRP. The backend itself never loads DJI's
native thermal libraries.

The native worker produces, per capture:

- Float32 Celsius `temperature.tif` in thermal-sensor pixel space.
- Display-only `preview.png`.
- Generic `hotspot-mask.png` and `hotspots.json` candidate analysis.
- `thermal.json` with SDK/R-JPEG provenance, measurement parameters/ranges,
  statistics, and explicit registration limitations.

It also produces job-level `capture-points.geojson`,
`thermal-summary.json`, `thermal-summary.csv`, and
`result-manifest.json`. Capture points use the source-image GPS only and are
marked `CAPTURE_CENTER_ONLY`; they do **not** georeference individual thermal
pixels or hotspot masks.

The worker's generic hotspot detector is deliberately not a PV/equipment defect
classifier. It identifies connected sensor-space regions above a configurable
median ΔT threshold so that later domain-specific inspection logic has a
repeatable candidate set.

The workflow is available only when the media dataset platform is `M3T` and at
least one complete Wide/Thermal capture pair exists.

```text
POST /api/v1/processing/thermogram
GET  /api/v1/processing/jobs/<UUID>/handoff
GET  /api/v1/processing/jobs/<UUID>/handoff/download
POST /api/v1/processing/jobs/<UUID>/external-claim
POST /api/v1/processing/jobs/<UUID>/external-status
```

The dedicated `external-claim` endpoint is used by automatic workers to claim a
job atomically. Status updates remain separately idempotent so retries after a
lost HTTP response do not create a second processing run.

For an integrated Linux x86-64 deployment, mount the DJI TSDK and enable the
optional Compose profile:

```dotenv
DJI_TSDK_HOST_PATH=/opt/dji-thermal-sdk
DJI_TSDK_VERSION=1.8_20251211
M3_THERMAL_HOTSPOT_DELTA_C=10
M3_THERMAL_HOTSPOT_MIN_PIXELS=4
```

```bash
docker compose --profile thermal up -d thermal-worker
```

The normal stack does not start the worker unless this profile is selected.

#### External Thermogram fallback

The versioned handoff remains usable with an external Thermogram/Windows
workflow or another processing tool that needs the untouched DJI folder. When a
workstation sees the media through a different path, configure its handoff
path, for example:

```dotenv
M3CLOUD_MEDIA_IMPORT_HANDOFF_ROOT=\\\\m3-cloud\\media-import
```

External/manual job states are tracked as `WAITING_EXTERNAL`,
`RUNNING_EXTERNAL`, `COMPLETED_EXTERNAL`, or `FAILED_EXTERNAL`. The same
handoff JSON contains the original relative paths, SHA-256 hashes, capture
groups, metadata snapshots, and result-drop path.

#### Thermal result return

Both the native worker and manual external tools return results through the
dedicated processing-import mount. Each processing job owns one drop folder:

```text
/processing-import/<job-uuid>/
```

Configure the host/share paths as needed:

```dotenv
M3CLOUD_PROCESSING_IMPORT_HOST_PATH=/mnt/m3-processing-import
M3CLOUD_PROCESSING_IMPORT_HANDOFF_ROOT=\\m3-cloud\processing-import
```

M3-Cloud snapshots each returned file, verifies that it did not change during
the copy, computes SHA-256, uploads it to the `m3-results` bucket, and
registers it as a normal `ProcessingResult`.

```text
GET  /api/v1/processing/jobs/<UUID>/external-results/status
POST /api/v1/processing/jobs/<UUID>/external-results/import
```

Native results are classified as temperature raster, thermal preview, hotspot
mask/analysis, capture-center GeoJSON, summary JSON/CSV, metadata, and manifest.
The Processing UI can preview thermal images/masks and map capture-center points
while keeping the sensor-space/georeferencing distinction explicit.

### Immutable processing input manifests

Every processing job stores a content snapshot of each selected original: relative path, byte
size, SHA-256, media kind, and capture group. The snapshot is independent from later media-catalog
updates.

```text
GET /api/v1/processing/jobs/<UUID>/inputs
GET /api/v1/processing/jobs/<UUID>/inputs/download
```

WebODM verifies each source file against this snapshot immediately before upload. A changed source
aborts processing instead of silently changing the job input.


### Automatic media-to-flight matching

DJI filenames such as `DJI_20260920120000_0001_W.JPG` contain local camera time but no
timezone offset. M3-Cloud can normalize that timestamp and conservatively associate a media
dataset with a recorded flight.

Configure the timezone that was active on the aircraft/controller when the media was captured:

```dotenv
M3CLOUD_MEDIA_FILENAME_TIMEZONE=Europe/Berlin
M3CLOUD_MEDIA_AUTO_MATCH_FLIGHTS=true
M3CLOUD_MEDIA_AUTO_MATCH_MARGIN_SECONDS=300
M3CLOUD_MEDIA_AUTO_MATCH_MAX_DISTANCE_M=100
M3CLOUD_MEDIA_AUTO_MATCH_MIN_GPS_FRACTION=0.8
M3CLOUD_MEDIA_AUTO_MATCH_MAX_GPS_SAMPLES=64
M3CLOUD_MEDIA_AUTO_MATCH_MAX_SAMPLE_TIME_DELTA_SECONDS=5
```

Automatic assignment is performed only when exactly one flight contains the complete dataset
capture window within the configured margin. Zero matches remain unassigned; multiple matches are
reported as `AMBIGUOUS`. A manual flight assignment is never overwritten by later scans.


### Processing input capture timestamps

Processing input snapshots also freeze each original's normalized capture time. This applies to
both WebODM and Thermogram jobs. Thermogram job creation now freezes the same path, byte size,
SHA-256, media kind, capture group, and capture timestamp contract as WebODM, so later media
catalog rescans cannot silently change an external handoff.


### EXIF / GPS / DJI XMP

The external media scanner reads metadata from the original files **without modifying them**.
For each catalogued image M3-Cloud stores a normalized metadata record plus a compact raw
EXIF/XMP representation.

Normalized fields include capture time and its provenance, camera/lens identity, dimensions,
exposure, ISO, focal length, EXIF GPS coordinates/altitude, DJI absolute and relative altitude,
aircraft attitude, and gimbal attitude. EXIF GPS coordinates are preferred when both EXIF and
DJI XMP coordinates exist. This is important for M3M data because the aircraft writes
sensor-position-compensated coordinates into the image EXIF.

Altitude references remain separate:

```text
EXIF GPS altitude        -> EXIF sea-level reference
DJI AbsoluteAltitude     -> DJI absolute/ellipsoid altitude
DJI RelativeAltitude     -> relative to takeoff point
```

Existing catalog entries are backfilled automatically on the next media scan via the metadata
schema version. Processing jobs freeze the normalized metadata together with size/hash/capture
time so later rescans cannot silently change the processing input manifest.


### Flight ↔ dataset validation

Automatic media-to-flight assignment is deliberately conservative and runs in two stages:

1. The complete dataset capture-time interval must fit inside the flight interval plus
   `M3CLOUD_MEDIA_AUTO_MATCH_MARGIN_SECONDS`.
2. If the media contains GPS metadata, sampled image positions are validated against the
   persisted PostGIS flight track. When an image also has a capture timestamp, its GPS
   position is compared with the temporally nearest persisted flight sample; the default
   maximum time delta is 5 seconds. GPS without an individual capture time falls back to
   nearest-track validation. By default at least 80% of sampled image positions must be
   within 100 m of the applicable flight position/track.

GPS never rescues a time-incompatible flight; it only confirms or rejects time candidates.
The maximum number of image GPS positions used per validation is bounded by
`M3CLOUD_MEDIA_AUTO_MATCH_MAX_GPS_SAMPLES` to keep rescans deterministic and inexpensive.

Match states:

```text
MATCHED_TIME_GPS   exactly one time candidate also passes GPS validation
MATCHED_TIME_ONLY  exactly one time candidate; dataset has no image GPS
AMBIGUOUS_TIME     more than one time candidate and no image GPS
AMBIGUOUS_GPS      more than one time candidate also passes GPS validation
GPS_REJECTED       time candidate(s) exist, but GPS disagrees with all tracked flights
GPS_UNVERIFIED     dataset has GPS, but candidate flight has no persisted track positions
NO_MATCH           no flight contains the dataset capture window
NO_CAPTURE_TIME    dataset has no usable capture time
MANUAL             operator-selected association; automatic matching will not replace it
```

The dataset API also exposes `flight_match_details`, including the configured distance
threshold, GPS sampling coverage, per-candidate track-point count, fraction of image positions
inside the threshold, median distance, maximum distance, and pass/reject status.


## Projects and surveys

M3-Cloud groups persistent work into Projects and Surveys without changing existing Flight,
MediaDataset, or ProcessingJob identifiers.

```text
Project
└── Survey
    ├── Flight
    ├── MediaDataset
    └── ProcessingJob
        ├── frozen ProcessingJobAsset inputs
        └── ProcessingResult outputs
```

A Survey can be created manually or directly from an imported media dataset. M3E defaults to
`MAPPING`, M3T to `THERMAL`, and M3M to `MULTISPECTRAL`. Existing explicit Survey
assignments are never overwritten by automatic propagation.

Relevant endpoints:

```text
GET  /api/v1/projects
POST /api/v1/projects
GET  /api/v1/projects/<project-id>/surveys
POST /api/v1/projects/<project-id>/surveys
POST /api/v1/projects/<project-id>/surveys/from-dataset/<dataset-id>
GET  /api/v1/surveys/<survey-id>/lineage
GET  /api/v1/surveys/<survey-id>/manifest
GET  /api/v1/surveys/<survey-id>/manifest/download
```

The Survey manifest is a point-in-time lineage export. It includes current Flight and MediaDataset
associations, original media hashes/metadata, immutable ProcessingJob input snapshots, and archived
ProcessingResult hashes/object keys. It does not modify or copy external originals.


## Mission handoff upload

Mission planning remains separated from aircraft execution. A READY revision can be sealed into an
immutable handoff package and, when explicitly enabled, that exact package can be uploaded into
Lyrebird's MAVLink mission store.

```dotenv
M3CLOUD_MISSION_UPLOAD_ENABLED=false
M3CLOUD_MISSION_UPLOAD_TIMEOUT_SECONDS=6
```

Upload uses the standard MAVLink mission handshake
`MISSION_COUNT -> MISSION_REQUEST_INT -> MISSION_ITEM_INT -> MISSION_ACK`. Before transfer,
M3-Cloud verifies the physical aircraft serial, a live MAVLink route, and Lyrebird's reported
`missionExecutor` against the executor sealed in the deployment. Upload is blocked while the
aircraft reports an ACTIVE or PAUSED mission.

```text
POST /api/v1/missions/<mission-id>/deployments/<deployment-id>/upload
```

The action only replaces/stores the mission plan. M3-Cloud still exposes no mission start, pause,
resume, land, RTH, or abort command. Old handoff packages sealed before upload support remain
audit-only because immutable packages are never rewritten.


After Lyrebird acknowledges an upload, M3-Cloud immediately performs a read-only mission-list
read-back. The returned `MISSION_ITEM_INT` records are fingerprinted with the same canonical CRC32
used for `MISSION_CURRENT.mission_id`. A deployment reaches `UPLOADED` only when that fingerprint
matches the immutable sealed package. An acknowledged upload that cannot be verified is retained
as `UPLOAD_UNVERIFIED` rather than being reported as a clean success.
