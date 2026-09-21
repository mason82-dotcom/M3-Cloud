# DJI Cloud API in M3-Cloud

## Current DJI state

The DJI Developer product page currently identifies **Cloud API 1.14.0** as the current release.
DJI Cloud API is not installed as a Python, npm or Gradle runtime package. It is a server protocol
surface built around MQTT, HTTPS and WebSocket, with DJI Pilot 2 or DJI Dock acting as the DJI-side
client.

M3-Cloud therefore keeps its production Cloud API implementation in the native FastAPI stack:

```text
backend/app/dji/
backend/app/api_dji.py
backend/app/api_dji_pilot.py
EMQX
Redis
PostgreSQL/PostGIS
```

Do not replace that production path with DJI's historical Spring Boot demo.

## One-command Windows development setup

For the Windows workstation used to build `com.lyrebird.rc`, run from the repository root:

```powershell
.\scripts\setup-dji-development.ps1
```

This resolves and verifies the already-pinned Android DJI dependencies (`MSDK 5.18.0`,
`networkImp 5.18.0`, `wpmzsdk 1.0.5.1`) through the Gradle wrapper and installs the official
Cloud API reference checkout under `.vendor/dji-cloud-api/`.

To include DJI's deprecated Cloud API demo for protocol comparison only:

```powershell
.\scripts\setup-dji-development.ps1 -IncludeDeprecatedCloudDemo
```

## Install the official reference material

Windows PowerShell:

```powershell
.\scripts\install-dji-cloud-api-reference.ps1
```

Linux/macOS:

```bash
bash scripts/install-dji-cloud-api-reference.sh
```

The scripts clone DJI's public `Cloud-API-Doc` repository into:

```text
.vendor/dji-cloud-api/Cloud-API-Doc
```

`.vendor/` is intentionally ignored by Git.

### Important version caveat

DJI's public `Cloud-API-Doc` GitHub mirror is not guaranteed to track the product website in lockstep.
At the time this integration was added, the DJI product page reported Cloud API 1.14.0 while the
latest public GitHub documentation commit was labelled `v1.11.3 released`. For current protocol
behaviour, treat `https://developer.dji.com/cloud-api/` and the live DJI developer documentation
as authoritative.

## Optional deprecated reference demo

DJI stopped maintaining `DJI-Cloud-API-Demo` and `Cloud-API-Demo-Web` on 2025-04-10 and warns that
the demo is not a production-grade service. It may still be useful to compare topic names, payload
models and JSBridge behaviour.

Install it only when explicitly needed:

```powershell
.\scripts\install-dji-cloud-api-reference.ps1 -IncludeDeprecatedDemo
```

or:

```bash
DJI_CLOUD_API_INCLUDE_DEPRECATED_DEMO=1 bash scripts/install-dji-cloud-api-reference.sh
```

Never expose the deprecated demo directly as the M3-Cloud production backend.

## DJI developer application

Cloud API itself requires a DJI **Cloud API application** in DJI Developer Center. The application
provides the values used by Pilot 2 license verification:

```dotenv
M3CLOUD_DJI_CLOUD_APP_ID=
M3CLOUD_DJI_CLOUD_APP_KEY=
M3CLOUD_DJI_CLOUD_APP_LICENSE=
```

Do not commit real credentials.

## M3-Cloud Pilot 2 connection

Enable the existing server integration with:

```dotenv
M3CLOUD_DJI_MQTT_ENABLED=true
M3CLOUD_DJI_PILOT_ENABLED=true
M3CLOUD_DJI_PILOT_BOOTSTRAP_TOKEN=<long-random-secret>
M3CLOUD_DJI_PILOT_MQTT_URL=tcp://<m3-cloud-host>:1883
M3CLOUD_DJI_WORKSPACE_ID=<stable-uuid>
```

Then start/rebuild M3-Cloud:

```bash
docker compose up -d --build
```

Pilot 2 Open Platform URL:

```text
http://<m3-cloud-host>:8080/pilot2/
```

Useful status endpoint:

```text
GET /api/v1/dji/pilot/status
```

See `docs/dji-pilot2.md` for the complete RC Pro Enterprise / Pilot 2 workflow.

## Coordination with the M3M multispectral workflow

Cloud API integration must not collapse M3E, M3T and M3M into one generic Mavic 3 Enterprise
camera model. M3-Cloud/Lyrebird already uses the MSDK `CameraType` as the authoritative
aircraft-side camera discriminator.

Current cross-component contract:

- `M3M_RGB_MULTISPECTRAL` remains the M3M survey capture profile.
- M3M capture/readback continues to use RGB + NDVI + G + R + RE + NIR MSDK sources.
- Cloud API topology must preserve undocumented/unknown DJI product type/subtype values instead
  of guessing an M3M identity from another Mavic 3 Enterprise variant.
- Cloud API work may transport flight, media, RTK and lineage metadata, but must not silently
  replace the dedicated M3M processing/handoff workflow.
- The multispectral processing boundary remains separate from this Cloud API installation work;
  M3-Cloud keeps planning, capture, media ingest, hashes, EXIF/XMP, RTK metadata and validated
  dataset lineage/handoff.

## Mobile SDK relationship

DJI Mobile SDK V5 remains a separate aircraft-side dependency used by `com.lyrebird.rc`.
The repository currently pins MSDK Android **5.18.0**. Cloud API does not replace it:

```text
com.lyrebird.rc + MSDK V5     -> custom RC application path
DJI Pilot 2 + Cloud API       -> DJI Open Platform cloud path
                         \
                          -> both may connect to M3-Cloud
```
