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

Initial repository scaffold. Functional implementation follows incrementally.
