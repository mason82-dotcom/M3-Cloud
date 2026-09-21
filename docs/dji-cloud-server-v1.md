# DJI Cloud API server v1

This branch is the server-side integration track for DJI Pilot 2 / RC Pro Enterprise.

## Collaboration boundary

The RC Pro / Lyrebird track owns:

- `lyrebird/LyrebirdApp/**`
- DJI MSDK V5 integration
- controller/aircraft/payload capability discovery and hardware readback
- local RC HTTP/camera/capture/streaming interfaces
- real Pilot 2 / RC Pro Enterprise validation captures

This server track owns:

- `backend/app/dji/**`
- DJI Cloud API MQTT gateway/router/transactions
- Pilot 2 HTTPS and WebSocket contracts
- topology / TSA projection
- wayline, media, map, liveview and cloud-control server endpoints
- Compose/EMQX/backend integration for the Cloud API control plane
- contract and integration tests

Shared contracts must be changed deliberately and tested on both sides.

## Platform rule

Every change is reviewed for M3E, M3T and M3M. Platform-specific camera/payload behavior is not copied blindly between aircraft. Undocumented DJI Cloud API product identifiers are never invented; unknown values remain unknown until verified from DJI documentation or real hardware.

## Initial server slice

The first slice upgrades Pilot 2 from the current MQTT-only bootstrap toward:

1. authenticated HTTPS API component;
2. authenticated Pilot WebSocket component;
3. TSA topology endpoint;
4. server-to-Pilot topology/OSD WebSocket fan-out.

Media, mission, map and liveshare remain disabled until their complete server contracts are integrated and tested.

## Branch policy

- Base: current `main`
- Server branch: `feature/dji-cloud-server-v1`
- Older `feature/dji-cloud-primary-core` is reference material only because it has diverged heavily from current `main`.
- No merge to `main` without explicit approval.
