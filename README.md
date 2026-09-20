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
