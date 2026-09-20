---
title: UgCS Integration
description: Flying Lyrebird from UgCS via the PX4 VSM over MAVLink 2, and how MAVLink mission-item fields map onto DJI's wayline model.
breadcrumb: Interfaces
---

UgCS can fly a Lyrebird-equipped aircraft as a generic PX4 vehicle, using UgCS's own PX4 vehicle service module (VSM) — no Lyrebird-side change is needed, since [MAVLink 2](/mavlink/) is already a full control surface. This page documents the connection topology and one MAVLink-to-DJI translation detail (heading) that is easy to get wrong from the UgCS side.

## Connection topology

```
UgCS
  │
  │  MAVLink 2 / UDP
  ▼
PX4 VSM                          (UgCS-side service; Lyrebird deliberately identifies
  │                               as MAV_AUTOPILOT_PX4 so generic GCS software shows
  ▼                               Fly/Plan views with no special-casing)
Lyrebird :14550
  │
  ├── MAVLink <-> DJI translation
  ├── RTK telemetry
  ├── Mission item execution (onboard or dji_native executor — see /missions/)
  ├── Camera / Gimbal
  ├── Safety authority (two-computer model, X-Safety-Token / MAVLink 2 signing)
  └── Flight / Survey logger (JSONL + mirrored DJI flight records)
          │
          ▼
DJI MSDK V5
  │
  ▼
Mavic 3E + RTK
  │
  ▼
RC Pro Enterprise
```

Notes on this diagram, checked against the current app code:

- There is no standalone "survey translation" module. Grid/survey waypoints arrive as an ordinary `MISSION_ITEM_INT` sequence and camera commands, handled by whichever [mission executor](/missions/) (`onboard` or `dji_native`) is configured — same code path as any other mission. `MAV_CMD_DO_SET_CAM_TRIGG_DIST` (distance-triggered capture, the trigger UgCS's own Photogrammetry tool emits) is now translated on the `dji_native` path into a `multipleDistance` wayline action group that fires DJI's own mechanical shutter as ground distance accumulates on the flight controller — see [Missions](/missions/#distance-triggered-capture-compiled-to-one-wayline-action-group).
- Safety authority is not a separate module either; it is `ControlAuthority`/`X-Safety-Token` logic threaded through the command and motion sinks, plus MAVLink 2 packet signing (`lb_mav_0_signing_key`) as the MAVLink-side equivalent.

### Reference PX4 VSM config

See `scripts/ugcs/px4_vsm_lyrebird.conf` in this repo for the UgCS-side connection block (`connection.udp_out.lyrebird.*`, `vehicle.px4.*`) and `scripts/configure_mavlink_gcs.sh` for setting the matching Lyrebird-side prefs via `adb`.

## Heading: UgCS → DJI wayline yaw

A per-waypoint heading set in UgCS survives translation into DJI's own wayline yaw model, through exactly one MAVLink field:

```
UgCS heading
      │
      ▼
MAVLink mission item param4        MissionItem.param4 (Float)
      │                            NaN  = "no explicit heading" (nose-forward)
      ▼                            any other value = absolute heading, degrees
Lyrebird
      │                            FlightDeckActivity.startNative():
      │                              heading = if (item.noseForward) null
      │                                         else item.param4.toDouble()
      ▼
DJI WaylineWaypointYawParam         WaylineMissionHelper.createWaypointFromLatLon():
      │                              yawMode = FIXED
      │                              yawAngle = headingDeg
      │                              yawPathMode = FOLLOW_BAD_ARC
      ▼
M3E
```

`createWaypointFromLatLon` actually has three branches, only the middle one is the "fixed heading" path above:

| Condition | DJI `yawMode` | Driven by |
|---|---|---|
| `DO_SET_ROI` / `DO_SET_ROI_LOCATION` active | `TOWARD_POI` | ROI target, not `param4` |
| `param4` is a real number | `FIXED` | `param4`, degrees |
| `param4` is `NaN` (default/unset) | `FOLLOW_WAYLINE` | nothing — DJI keeps nose along the flight path |

**Practical consequence for UgCS mission plans:** a waypoint must carry an explicit numeric heading (0-360°) in `param4` to get a fixed DJI heading; leaving the field empty/`NaN` silently falls back to nose-forward. If UgCS instead expresses "look at" behavior via a separate `DO_SET_ROI`/`DO_SET_ROI_LOCATION` item, that resolves to `TOWARD_POI`, which is geometrically a continuously-computed bearing toward a point — not the same thing as a fixed compass heading — and takes priority over `param4` while active.

## Photogrammetry: UgCS's Grid/Corridor tools

UgCS's Photogrammetry planner computes a full survey grid from camera model, target GSD (ground
sample distance), and forward/side overlap — altitude, line spacing, and photo spacing are all
derived, not entered by hand. Example, Mavic 3E camera:

```
GSD              2.0 cm/px
Forward overlap  80 %
Side overlap     70 %

      ↓

UgCS computes

Altitude          73 m
Line spacing      31 m
Photo spacing     11.6 m
Images            438
```

None of that computation happens on the Lyrebird/aircraft side — UgCS hands over a finished plan of
ordinary MAVLink items, and Lyrebird translates each one exactly as it would any other mission
(see [Heading](#heading-ugcs--dji-wayline-yaw) above and the [Missions](/missions/) translation
table):

```
UgCS Photogrammetry
       │
       ├── waypoint            →  NAV_WAYPOINT        →  WaylineWaypoint
       ├── speed               →  DO_CHANGE_SPEED      →  waypoint.speed
       ├── gimbal -90°         →  DO_GIMBAL_MANAGER_*  →  GIMBAL_ROTATE (+ waypoint default nadir)
       └── camera by distance  →  DO_SET_CAM_TRIGG_DIST →  MULTIPLE_DISTANCE
                │
                ▼
             Lyrebird
                │
                ▼
       DJI Native Wayline (dji_native executor)
                │
        MULTIPLE_DISTANCE action group
                │
                ▼
        M3E mechanical shutter
```

The 438-image grid above compiles to **one** `multipleDistance` wayline action group spanning the
whole survey leg (or one per leg, if the grid has more than one contiguous run) — not 438 individual
trigger actions. DJI's flight controller fires the shutter itself as it accumulates the configured
ground distance, independent of the app's own execution loop; see
[Missions](/missions/#distance-triggered-capture-compiled-to-one-wayline-action-group) for how the
translator builds that action group.

**Corridor missions** work the same way, with one difference: a corridor typically sets a distinct
heading (`param4`) per waypoint — perpendicular or parallel to the corridor axis — rather than one
heading for the whole grid. That is already handled per-waypoint (see the heading table above); the
distance trigger itself is heading-independent and needs no special-casing for corridors.

## RTK: resolved aircraft position and fix type

`GPS_RAW_INT` and `GLOBAL_POSITION_INT` use Lyrebird's **resolved aircraft position**. The raw
flight-controller location is always sampled first. When RTK is enabled, connected, healthy,
fresh, reports `FLOAT` or `FIXED_POINT`, and DJI's `RTKLocationInfo.real3DLocation` contains
valid coordinates, Lyrebird substitutes **only horizontal latitude/longitude** with that DJI
RTK-fused position. Otherwise it uses the flight-controller coordinates unchanged.

Vertical MAVLink altitude intentionally stays on the flight-controller/take-off reference path:
`takeoff AMSL + relative-to-takeoff altitude` when available, with the flight-controller altitude
as fallback. `real3DLocation.altitude` is logged for analysis but is not mixed into MAVLink altitude
until its reference can be proven compatible.

```
                              fresh healthy RTK FLOAT/FIXED?
Flight-controller position ───────────────┬───────────────┐
                                         │ no            │ yes
                                         ▼               ▼
                                  FC latitude/lon   real3D latitude/lon
                                         └───────┬───────┘
                                                 ▼
                                      resolved MAVLink position

GPS_RAW_INT          → resolved position + real RTK fix_type
GLOBAL_POSITION_INT  → resolved position
```

Only the **fix type** on `GPS_RAW_INT` comes from RTK state, via
`RtkTelemetryMonitor` cross-checking DJI's `RTKPositioningSolution` against RTK enablement,
link health and update freshness. A stale fix is never left advertised as RTK FIX:

| DJI `RTKPositioningSolution` (fresh, enabled, healthy, connected) | MAVLink `fix_type` |
|---|---|
| `NONE` | `GPS_FIX_TYPE_NO_FIX` |
| `SINGLE_POINT` | `GPS_FIX_TYPE_3D` |
| `FLOAT` | `GPS_FIX_TYPE_RTK_FLOAT` |
| `FIXED_POINT` | `GPS_FIX_TYPE_RTK_FIXED` |
| stale / disconnected / unknown | falls back to ordinary GNSS quality |

The per-mission survey CSV is written beside the current Lyrebird flight JSONL log. For every
camera-generated-media event it preserves these sources separately:

- `latitude/longitude` + `position_source`: the resolved position actually exported to MAVLink.
- `fc_latitude/fc_longitude/fc_altitude_m`: the raw flight-controller read.
- `rtk_latitude/rtk_longitude/rtk_altitude_m`: DJI
  `RTKLocation.mobileStationLocation` (raw RTK/mobile-station position).
- `rtk_fused_latitude/rtk_fused_longitude/rtk_fused_altitude_m`: DJI
  `RTKLocationInfo.real3DLocation`.
- `rtk_enabled/rtk_connected/rtk_healthy`, fix, age and standard deviations: quality context for
  that same capture.

A single immutable RTK snapshot is used for both position resolution and the survey record, so an
RTK callback cannot make the coordinates and fix metadata refer to different update epochs.

## NTRIP / Custom Network RTK credentials

Lyrebird's existing Custom Network RTK UI (`RTKCenterFragment` → "Set custom network RTK account
information") accepts NTRIP server/port/username/password/mountpoint interactively. For a caster
used on every flight (e.g. a SAPOS/VRS mountpoint), default credentials can instead be baked into
the build:

```
local.properties (gitignored, per-machine)      BuildConfig                          RTKNetworkVM
  NTRIP_SERVER_ADDRESS  ──────────────→  BuildConfig.NTRIP_SERVER_ADDRESS  ──→  hasDefaultNtripSettings()
  NTRIP_PORT             ──────────────→  BuildConfig.NTRIP_PORT            ──→  startDefaultNtripService()
  NTRIP_USERNAME          ────────────→  BuildConfig.NTRIP_USERNAME
  NTRIP_PASSWORD          ────────────→  BuildConfig.NTRIP_PASSWORD
  NTRIP_MOUNT_POINT       ────────────→  BuildConfig.NTRIP_MOUNT_POINT
```

A "Start Default NTRIP RTK" button appears on the RTK Network page only when both
`NTRIP_SERVER_ADDRESS` and `NTRIP_USERNAME` are non-blank at build time; otherwise the page behaves
exactly as before and the manual dialog remains the only way in. Never commit real credentials —
`local.properties` is gitignored per-machine, matching how `AIRCRAFT_API_KEY` is already handled;
see `LyrebirdApp/android-sdk-v5-as/local.properties.example` for the template.
