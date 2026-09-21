---
title: Missions
description: How a QGroundControl-uploaded plan is stored, translated, and flown — either by Lyrebird's own PID sequencer or by DJI's native wayline engine.
breadcrumb: Interfaces
---

Lyrebird accepts a mission the way any MAVLink autopilot does: QGroundControl's Plan view uploads a
list of `MISSION_ITEM_INT` messages, and pressing Start flies it. What happens between those two
moments — how the plan is stored, and how it is actually flown on an airframe with no MAVLink
autopilot underneath — is what this page covers. [Why QGC shows the Plan and Start controls at
all](/mavlink/#why-it-looks-like-px4-to-qgroundcontrol) is a separate, prerequisite trick; this page
assumes that part already works and focuses on the mission itself.

## Flying a plan from QGroundControl

1. Enable `lb_mav_0_enabled` and `lb_mav_0_allow_flight` (both preferences, off by default — see
   [MAVLink 2 Interface](/mavlink/)). The RC and QGC need to share a LAN; QGC listens on UDP 14550.
2. Build a plan in QGC's **Plan** view: waypoints, and optionally a leading **Takeoff**, a trailing
   **Land** or **RTL**, **Camera** (photo/video) items, **Gimbal Pitch** items, a **Change Speed**
   item, and a **ROI Location** item.
3. **Upload** it. Lyrebird's upload handshake (`MavlinkMissionStore`) requests each item, refuses
   the whole transfer if any item's command is not one it understands, and — deliberately — stores
   every accepted item **exactly as MAVLink sent it**, in wire format. Translation to DJI's shape
   happens only when the mission starts, on a copy, which is what lets a later download return
   precisely what was uploaded regardless of how it was flown.
4. Arm and switch to **Mission mode** (or press QGC's **Start Mission**). `SET_MODE(AUTO.MISSION)`
   and the `MISSION_START` that follows both route to whichever executor `lb_mission_exec` selects.
5. Watch progress in QGC as usual: `MISSION_CURRENT` and `MISSION_ITEM_REACHED` are reported by
   both executors, though not with identical precision — see the comparison below.

## Two executors

MAVLink has one mission protocol; Lyrebird has two ways to fly what it uploads. Which one runs is a
preference (`lb_mission_exec`, values `onboard` or `dji_native`), because a ground station has no
MAVLink concept for picking one — there is nothing to negotiate over the wire.

| | `dji_native` (default) | `onboard` |
| --- | --- | --- |
| Who flies it | DJI's own wayline engine, on the flight controller | Lyrebird's app, sequencing legs through its PID waypoint controllers |
| Survives the phone losing focus / being backgrounded | Yes — the mission lives on the aircraft once pushed | No — the sequencing loop lives in the app |
| Take-off, land, RTL | Handled by DJI, from the plan's leading `NAV_TAKEOFF` altitude and trailing `NAV_LAND`/`NAV_RETURN_TO_LAUNCH` | Handled item-by-item like any other plan item |
| Per-item heading (`param4`) | Honoured, as a fixed wayline yaw | Honoured |
| Per-leg speed (`DO_CHANGE_SPEED`) | Honoured, as a per-waypoint speed | Honoured |
| Camera / gimbal actions | Translated to wayline actions, triggered on reaching the waypoint they sit after | Executed directly, in plan order |
| Distance-triggered capture (`DO_SET_CAM_TRIGG_DIST`) | Compiled to a native `MULTIPLE_DISTANCE` action group across the active waypoint span | Rejected; camera-by-distance requires the DJI-native executor |
| Progress reporting | `MISSION_CURRENT` per waypoint reached; no per-item `MISSION_ITEM_REACHED` | Exact `MISSION_ITEM_REACHED` per item |
| `MAV_CMD_SET_CAMERA_MODE` | No wayline equivalent — skipped | Honoured |

**Default is `dji_native`.** A mission that keeps running on DJI's own flight controller is not at
the mercy of the app being backgrounded, the phone locking, or Android killing a background
process mid-flight — the failure mode that matters most for an unattended or long mission. Switch
to `onboard` for a plan that leans on something only it can do: a continuously-tracking ROI, or
exact per-item arrival reporting.

**Switching it.** `lb_mission_exec` is an Android `SharedPreferences` value (file `LyrebirdPrefs`,
package `com.lyrebird.rc`), the same way every other `lb_*` preference in this app is set — by hand
in the field, via `adb` or the settings backup file, not through a settings screen or a MAVLink
parameter. There is nothing to edit for the default.

## What the native path translates

Pushing a plan to DJI's wayline engine means building a
[WPML](https://github.com/dji-sdk/Cloud-API-Doc/blob/master/docs/en/60.api-reference/00.dji-wpml/30.waylines-wpml.md)
mission (a KMZ file), not reusing MAVLink's own item list, so each plan item becomes whichever
WPML construct has the matching meaning:

| MAVLink item | Wayline construct |
| --- | --- |
| `NAV_WAYPOINT` | A `wpml:waypoint`, at the item's lat/lon/alt |
| `NAV_TAKEOFF` (leading item, altitude) | Mission config `securityTakeOffHeight` — DJI climbs to it before flying to the first waypoint, on its own, as part of every wayline mission |
| `NAV_LAND` / `NAV_RETURN_TO_LAUNCH` (trailing item) | Mission config `finishAction`: `autoLand` / `goHome` |
| `param4` (heading) | Waypoint yaw mode `FIXED`, holding that heading |
| `DO_CHANGE_SPEED` | The waypoint's own `speed` field, applying to the legs that follow it, exactly like the onboard executor's running-speed variable |
| `IMAGE_START_CAPTURE` / `VIDEO_START_CAPTURE` / `VIDEO_STOP_CAPTURE` | A `takePhoto` / `startRecord` / `stopRecord` wayline action, triggered on reaching the waypoint the item sits after |
| `DO_GIMBAL_MANAGER_PITCHYAW` | A `gimbalRotate` wayline action, absolute pitch/yaw |
| `DO_SET_CAM_TRIGG_DIST` | A `multipleDistance` wayline action group using `param1` as the distance interval. `param3`/`param4` are preserved for diagnostics but not assigned DJI-specific semantics — see below |
| `DO_SET_ROI_LOCATION` / `DO_SET_ROI` (location mode) | Waypoint yaw mode `towardPOI` + gimbal heading mode `towardPOI`, both pointed at the ROI coordinate — see below |
| `DO_SET_ROI_NONE` / `DO_SET_ROI` (non-location mode) | Clears the active ROI for waypoints that follow |
| `SET_CAMERA_MODE` | No wayline equivalent — skipped |

An action item with no later waypoint to attach to (one that sits after the last leg, before a
trailing land) rides along with the last waypoint instead of being lost.

### Region of interest, compiled rather than dropped

MAVLink's ROI is modal: `DO_SET_ROI_LOCATION` puts the vehicle into "point at this coordinate" until
a later `DO_SET_ROI_NONE` (or a non-location `DO_SET_ROI`) clears it — the same kind of state a
ground station itself has to track across a plan. The native translator carries the same state
across the item list while it builds waypoints, and every waypoint built while an ROI is active gets
DJI's own `towardPOI` yaw mode plus `towardPOI` gimbal heading mode, both referencing the same target
coordinate.

That is a real, native DJI mechanism, not an approximation: `towardPOI` computes the aircraft's
heading and the gimbal's pitch/yaw toward the target **continuously while flying the leg**, on the
flight controller, the same way it would for a manually-built wayline mission in DJI's own app — not
a value calculated once and held fixed until the next waypoint. What it cannot do is track a *moving*
target: a wayline mission is compiled once before flight, so an ROI that MAVLink would keep updating
in real time can only be captured as wherever it was when the plan was built. A mission that needs a
moving ROI has to use `onboard`, which re-reads the live ROI command like a normal autonomous action.

### Distance-triggered capture, compiled to one wayline action group

`DO_SET_CAM_TRIGG_DIST` is modal, the same way ROI is: `param1 > 0` (re)starts triggering a photo
every `param1` metres of ground travel from that item on; `param1 == 0` stops it. Lyrebird deliberately
uses only `param1` for DJI native distance capture: `param3` is dialect-sensitive across MAVLink
implementations and `param4` is not repurposed as a DJI camera/payload index. A survey/grid
plan from a photogrammetry planner (UgCS, QGC's Survey tool) typically emits exactly one of these
before the grid's waypoints and one `param1 == 0` after — or never turns it off, letting the
mission's end close it implicitly.

The native translator (`WaylineMissionHelper.SurveyDistanceCapture`) tracks the open/closed span the
same way it tracks ROI: walking the item list, it opens a span at the first waypoint following a
`param1 > 0` item and closes it — inclusive — at the waypoint immediately before whatever ends it
(a `param1 == 0` item, a later `DO_SET_CAM_TRIGG_DIST` starting a new span, or simply the plan's last
waypoint). Each closed span becomes **one** `WaylineActionGroup` with a `MULTIPLE_DISTANCE` trigger
covering that whole `startWaypoint..endWaypoint` range and a single `TAKE_PHOTO` action — not one
action per waypoint. A grid with a few hundred photos compiles to one trigger group per contiguous
survey leg, not one action per photo; DJI's own wayline engine fires the mechanical shutter on the
flight controller as ground distance accumulates, independent of the app's own execution loop.

This groups separately from the per-waypoint `REACH_POINT` action groups the rest of this table
builds — a `MULTIPLE_DISTANCE` group is not tied to any single waypoint's arrival, so it cannot be
folded into them.

### Camera profile is verified before a native survey starts

A distance-triggered mission does not assume that every Mavic 3 camera stores the same sources.
Immediately before the KMZ is launched, Lyrebird identifies the attached MSDK camera type and
selects the platform-specific default survey profile:

| Platform | Survey profile | Stored sources |
|---|---|---|
| M3E | `M3E_MAPPING` | `WIDE_CAMERA` |
| M3T | `M3T_WIDE` | `WIDE_CAMERA` |
| M3M | `M3M_RGB_MULTISPECTRAL` | RGB, NDVI, G, R, red-edge and NIR MSDK sources |

The app switches to `PHOTO_NORMAL`, writes `KeyCaptureCameraStreamSettings`, performs a fresh
readback, and only launches the native mission if the returned source set matches the requested
profile. A camera/profile mismatch or missing source therefore fails before take-off rather than
silently flying a survey with the wrong dataset.

The wayline action itself continues to use DJI payload position `0`. This is independent of which
lens/source set is stored. `DO_SET_CAM_TRIGG_DIST.param4` is preserved for diagnostics but is not
reinterpreted as a DJI payload selector.

See [Enterprise Camera Platforms](/camera-platforms/) for the full M3E/M3T/M3M policy.

### Survey completion and report finalization

MSDK 5.18 can report a native wayline as `FINISHED` both after a natural completion and after
`stopMission()`. Lyrebird therefore tracks its own finish reason instead of treating every
`FINISHED` state as success. Survey reports distinguish `mission_finished`,
`mission_stopped`, `mission_interrupted`, disconnect/start/upload failures and other terminal
reasons.

After a survey ends, generated-media events are still accepted until the camera has been quiet long
enough (with a hard maximum wait) before media reconciliation begins. The resulting
`*_captures.csv` and `*_survey-summary.json` files are registered as the latest completed survey
and can be downloaded through the [HTTP API](/http-api/).

## Onboard, for comparison

The `onboard` executor is the simpler of the two conceptually: a loop in the app walks the item list
in order, flies each waypoint through Lyrebird's own PID controllers (`flyToWaypointNoseForward` for
`param4 = NaN`, `flyToWaypointHoldHeading` otherwise), and executes every non-waypoint item in place
— camera, gimbal, ROI, speed change — before moving to the next leg. `NAV_TAKEOFF` blocks the
sequencer until the aircraft is confirmed airborne before it lets the loop continue to the first
waypoint, the same transition [`climbAfterTakeoff`](https://github.com/SDU-UAS-Center/lyrebird/blob/main/LyrebirdApp/lyrebird-app/src/main/java/com/lyrebird/rc/FlightDeckActivity.kt)
waits for elsewhere in the app — issuing a waypoint leg while DJI's own take-off climb is still
running would have the two fight each other for the sticks. Because the loop lives in the app, it
reports an exact `MISSION_CURRENT`/`MISSION_ITEM_REACHED` for every single item, and it is the only
executor that can track a live-updating ROI target — at the cost of the mission depending on the app
staying alive and in the foreground for its whole duration.

## Verifying a translation

Neither executor changes what a download reports: `MavlinkMissionStore` always answers with the
verbatim uploaded items, regardless of which executor flew them or what it turned them into. Reading
a plan back after flying it is the fastest way to confirm nothing about the *stored* mission changed
— the translation lives entirely between `MISSION_START` and the aircraft's motion.
