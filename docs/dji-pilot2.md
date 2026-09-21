# DJI Pilot 2 → M3-Cloud

This is the first, intentionally narrow DJI Pilot 2 Cloud API integration stage.

## Scope

Implemented now:

- DJI Cloud API application/license verification through Pilot 2 JSBridge.
- Pilot 2 `thing` module loading.
- Pilot 2 MQTT connection to M3-Cloud's externally reachable EMQX listener.
- Stable workspace ID and platform/workspace labels.
- Existing M3-Cloud MQTT ingestion for topology, OSD and state telemetry.

Not loaded yet:

- `api`
- `ws`
- `map`
- `tsa`
- `media`
- `mission`
- `liveshare`

Those modules depend on DJI-specific HTTPS/WebSocket contracts that M3-Cloud does not yet fully
implement. The Pilot page therefore fails closed instead of advertising functions that only partly
work.

## Server configuration

Create a DJI **Cloud API** application in DJI Developer Center and put its three license values in
`.env`. Do not commit real values.

```dotenv
M3CLOUD_DJI_MQTT_ENABLED=true

M3CLOUD_DJI_PILOT_ENABLED=true
M3CLOUD_DJI_PILOT_BOOTSTRAP_TOKEN=<long-random-secret>

M3CLOUD_DJI_CLOUD_APP_ID=<DJI-app-id>
M3CLOUD_DJI_CLOUD_APP_KEY=<DJI-app-key>
M3CLOUD_DJI_CLOUD_APP_LICENSE=<DJI-app-license>

# Address as seen by RC Pro Enterprise, not Docker's internal "emqx" hostname.
# DJI Pilot 2 JSBridge documents tcp:// and ws:// for the thing module.
M3CLOUD_DJI_PILOT_MQTT_URL=tcp://<m3-cloud-host>:1883
M3CLOUD_DJI_PILOT_MQTT_USERNAME=
M3CLOUD_DJI_PILOT_MQTT_PASSWORD=

# Generate once, keep stable for this workspace:
M3CLOUD_DJI_WORKSPACE_ID=<uuid>
M3CLOUD_DJI_PLATFORM_NAME=M3-Cloud
M3CLOUD_DJI_WORKSPACE_NAME=M3-Cloud
M3CLOUD_DJI_WORKSPACE_DESCRIPTION=M3-Cloud DJI Pilot 2 workspace
```

Generate the two local secrets, for example:

```bash
python - <<'PY'
import secrets, uuid
print("bootstrap:", secrets.token_urlsafe(32))
print("workspace:", uuid.uuid4())
PY
```

Then rebuild/restart:

```bash
docker compose up -d --build
```

## DJI Pilot 2

On RC Pro Enterprise:

1. Open **DJI Pilot 2**.
2. Open **Cloud Services**.
3. Open **Open Platforms**.
4. Configure the M3-Cloud access URL:

   ```text
   http://<m3-cloud-host>:8080/pilot2/
   ```

   Use HTTPS in deployments that leave a trusted private LAN.

5. Open the platform page.
6. Enter `M3CLOUD_DJI_PILOT_BOOTSTRAP_TOKEN`.
7. Press **Pilot 2 mit M3-Cloud verbinden**.

Expected status:

```text
JSBridge      verfügbar
License       VERIFIED
Thing module  CONNECTED
Workspace     M3-Cloud
```

The backend should then receive `sys/product/<RC-SN>/status` and the aircraft
`thing/product/<aircraft-SN>/osd|state` topics.

The bootstrap operation uses `POST /api/v1/dji/pilot/bootstrap` and marks the response
`Cache-Control: no-store`, because it necessarily contains the Cloud API license material and
Pilot MQTT credentials. A non-secret readiness view is available at:

```text
GET /api/v1/dji/pilot/status
```

## Platform separation

M3-Cloud keeps platform identity explicit:

- M3E: RGB/Wide mapping camera path.
- M3T: Wide/Zoom/Thermal path.
- M3M: RGB + multispectral path.

Do not infer one platform's camera channels from another platform's payload fields.

The current DJI Cloud API product-support table explicitly lists M3E (type 77/sub-type 0), M3T
(type 77/sub-type 1), M3TA (77/3) and RC Pro Enterprise (type 144/sub-type 0), but does not list an
M3M aircraft entry there. DJI's current WPML documentation does list M3M as a supported mission
platform. Therefore M3M Cloud-API topology/telemetry remains a hardware-verification item. The registry
does **not** map an undocumented `77/2` value to M3M; unknown values remain
`DJI_TYPE_<type>_<subtype>` until an actual Pilot 2/M3M run or updated DJI Cloud API
documentation establishes the identity.

## Security boundary

The bootstrap endpoint returns the DJI Cloud API license and Pilot MQTT credentials because Pilot 2
needs them to establish its JSBridge cloud session. It therefore requires the
`X-M3-Pilot-Bootstrap` secret and is disabled by default.

The current EMQX development configuration may still allow anonymous MQTT access. Before using this
outside a trusted LAN, add broker authentication/ACLs and TLS. Pilot 2 and the M3-Cloud backend
should use separate MQTT identities so the Pilot account can publish only its DJI device topics and
the backend account can subscribe/reply as required.
