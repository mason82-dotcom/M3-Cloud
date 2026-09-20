# M3-Cloud Frontend

Initial operations UI for the M3-Cloud platform.

## Current integration
- Fleet/RTK overview
- MapLibre GL JS 6.10.0 map
- DJI Cloud API / Lyrebird source indicators
- Backend health polling via `/api/v1/system/health`
- Vehicle polling via `/api/v1/vehicles`
- Navigation placeholders for missions, liveview, media, processing and system

The UI intentionally keeps Lyrebird as a separate subsystem. M3-Cloud consumes normalized backend data rather than importing Lyrebird's test UI directly.

For development, serve this directory through a local HTTP server or the M3-Cloud reverse proxy. Opening `index.html` directly as a file is not recommended because ES modules and API calls require HTTP.
