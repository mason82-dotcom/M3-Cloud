# DJI Pilot 2 → M3-Cloud

M3-Cloud now uses DJI Cloud API as the primary Pilot-to-Cloud integration path for RC Pro Enterprise and the Mavic 3 Enterprise family.

## Implemented scope

The Pilot 2 page at `/pilot` bootstraps the DJI JSBridge only after a local M3-Cloud bootstrap token is supplied. The backend then exposes the modules that are actually implemented:

- `thing`: DJI MQTT topology, OSD, state, events, requests, service replies and property replies.
- `api`: DJI Pilot HTTPS contracts with `X-Auth-Token`.
- `ws`: authenticated Pilot WebSocket at `/ws/dji-pilot`.
- `map`: map element groups/elements.
- `tsa`: situation-awareness topology and WebSocket pushes.
- `liveshare`: DJI live-view control/status integration.
- `media`: enabled when Pilot media object storage is configured.
- `mission`: enabled only when the DJI-documented wayline storage provider is configured.

For storage, DJI documents `minio`, `aws` and `ali` for Pilot media uploads, but only `aws` and `ali` for the wayline-library STS contract. M3-Cloud therefore does not advertise the mission component when the provider is MinIO.

Cloud-control/DRC infrastructure is also present: authorization request/release, `drc_mode_enter`, DRC uplink ingestion, initial-state subscription and heartbeat/session lifecycle. Aircraft movement commands are intentionally not exposed yet.

## Required configuration

Create a DJI Cloud API application in DJI Developer Center and configure `.env`. Do not commit real credentials.

```dotenv
M3CLOUD_DJI_MQTT_ENABLED=true

M3CLOUD_DJI_PILOT_ENABLED=true
M3CLOUD_DJI_PILOT_BOOTSTRAP_TOKEN=<long-random-local-secret>

M3CLOUD_DJI_PILOT_APP_ID=<DJI-app-id>
M3CLOUD_DJI_PILOT_APP_KEY=<DJI-app-key>
M3CLOUD_DJI_PILOT_LICENSE=<DJI-app-license>

M3CLOUD_DJI_PILOT_WORKSPACE_ID=<stable-uuid>
M3CLOUD_DJI_PILOT_PLATFORM_NAME=M3-Cloud
M3CLOUD_DJI_PILOT_WORKSPACE_NAME=M3-Cloud
M3CLOUD_DJI_PILOT_WORKSPACE_DESC=Self-hosted DJI Enterprise operations

# Address as seen by RC Pro Enterprise, never Docker's internal "emqx" hostname.
M3CLOUD_DJI_PILOT_MQTT_URL=tcp://<m3-cloud-host>:1883
M3CLOUD_DJI_PILOT_MQTT_USERNAME=<pilot-mqtt-user>
M3CLOUD_DJI_PILOT_MQTT_PASSWORD=<pilot-mqtt-password>

# Public HTTP origin used by Pilot's HTTPS modules. Blank uses the page origin.
M3CLOUD_DJI_PILOT_API_URL=http://<m3-cloud-host>:8080
M3CLOUD_DJI_PILOT_API_TOKEN=<long-random-pilot-api-token>

# Reachable from RC Pro Enterprise.
M3CLOUD_DJI_PILOT_WS_URL=ws://<m3-cloud-host>:8080/ws/dji-pilot
```

Generate the local secrets and workspace UUID independently, for example:

```bash
python - <<'PY'
import secrets, uuid
print("bootstrap:", secrets.token_urlsafe(32))
print("pilot-api:", secrets.token_urlsafe(32))
print("control-api:", secrets.token_urlsafe(32))
print("workspace:", uuid.uuid4())
PY
```

The mutating M3-Cloud DJI control endpoints use a separate server-side token:

```dotenv
M3CLOUD_DJI_CONTROL_API_TOKEN=<long-random-control-token>
```

Clients calling live-view or cloud-control mutation endpoints send it as `X-M3Cloud-Control-Token`.

## Media and mission storage

For Pilot media uploads with the bundled S3-compatible storage:

```dotenv
M3CLOUD_DJI_PILOT_STORAGE_ENDPOINT=http://<m3-cloud-host>:8333
M3CLOUD_DJI_PILOT_STORAGE_STS_ENDPOINT=http://seaweedfs:8333
M3CLOUD_DJI_PILOT_STORAGE_PROVIDER=minio
M3CLOUD_DJI_PILOT_STORAGE_BUCKET=m3-media
M3CLOUD_DJI_PILOT_STORAGE_STS_MODE=federation_token
```

This enables `media` but deliberately leaves `mission` disabled. To advertise the DJI wayline-library component, configure a supported `aws` or `ali` object-storage backend and matching STS credentials.

## DJI Pilot 2 setup

On RC Pro Enterprise:

1. Open **DJI Pilot 2 → Cloud Services → Open Platforms**.
2. Set the M3-Cloud page to `http://<m3-cloud-host>:8080/pilot` (use HTTPS outside a trusted private LAN).
3. Open the page.
4. Enter `M3CLOUD_DJI_PILOT_BOOTSTRAP_TOKEN`.
5. Select **Connect Pilot 2**.

The bootstrap request is:

```text
POST /api/v1/dji/pilot/bootstrap
X-M3-Pilot-Bootstrap: <bootstrap-token>
```

The response is marked `Cache-Control: no-store` because it necessarily contains DJI license material and Pilot connection credentials. The old unauthenticated GET bootstrap no longer exists. `/pilot2/` is only a compatibility redirect to `/pilot`.

A non-secret readiness view remains available at:

```text
GET /api/v1/dji/pilot/status
```

## Connection readiness

The Pilot UI does not declare the cloud link ready solely because Pilot's own MQTT connection succeeded. It also checks the M3-Cloud backend DJI consumer health. This prevents a false-ready state when Pilot can reach the broker but the backend MQTT client is rejected or disconnected.

The WebSocket connection is authenticated before acceptance. Pilot supplies the configured API token as the `x-auth-token` query parameter.

## Platform separation

M3-Cloud keeps aircraft/payload identities separate:

- M3E: mapping RGB/wide path.
- M3T: wide/zoom/thermal path.
- M3TA: documented Cloud API subtype where applicable.
- M3M: supported in MSDK/WPML mission generation, including WPML aircraft type 77/subtype 2 and payload type 68.

The current DJI Cloud API product-support table does not document M3M as Pilot Cloud aircraft identity `77/2`. M3-Cloud therefore does not infer that topology identity; unknown Cloud API identities remain `DJI_TYPE_<type>_<subtype>` until verified from DJI documentation or hardware captures.

## DRC configuration

The DRC broker address is supplied by M3-Cloud in the DJI `drc_mode_enter` service payload and must be reachable from RC Pro Enterprise:

```dotenv
M3CLOUD_DJI_DRC_BROKER_ADDRESS=<host>:1883
M3CLOUD_DJI_DRC_CLIENT_ID_PREFIX=m3cloud-drc-
M3CLOUD_DJI_DRC_USERNAME=<dedicated-drc-user>
M3CLOUD_DJI_DRC_PASSWORD=<dedicated-drc-password>
M3CLOUD_DJI_DRC_ENABLE_TLS=false
M3CLOUD_DJI_DRC_CREDENTIAL_TTL_SECONDS=3600
M3CLOUD_DJI_DRC_OSD_FREQUENCY_HZ=10
M3CLOUD_DJI_DRC_HSI_FREQUENCY_HZ=1
M3CLOUD_DJI_DRC_HEARTBEAT_INTERVAL_SECONDS=5
```

The current implementation requires reported `is_cloud_control_auth=true` before entering DRC. After successful `drc_mode_enter`, it sends `drc_initial_state_subscribe` and periodic `heart_beat` packets. DRC sessions stop on cloud-control release or backend shutdown.

## Security boundary

Use separate identities/secrets for:

- Pilot bootstrap authentication.
- Pilot HTTPS/WebSocket API authentication.
- Backend DJI MQTT client.
- Pilot MQTT client.
- DRC broker client.
- M3-Cloud mutating control API.

The bundled development EMQX configuration must not be treated as an Internet-facing production security boundary. Before exposing it outside a trusted LAN, add authentication, topic ACLs and TLS.
