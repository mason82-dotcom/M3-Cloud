#!/usr/bin/env bash
# Configure Lyrebird's MAVLink 2 endpoint prefs on a connected RC/phone via adb, so an
# external MAVLink 2 ground station (e.g. UgCS with the PX4 VSM) can fly it.
#
# Requires a debuggable Lyrebird build (the default debug APKs are), because it edits
# LyrebirdPrefs.xml through `run-as` rather than a rooted shell.
#
# What this does NOT do: it does not flip lb_mav_0_allow_flight to true on its own if
# the preferences file does not exist yet (i.e. the app has never been launched). Flight
# motion over MAVLink is a safety-relevant switch that ships with an in-app confirmation
# dialog for a reason -- launch the app once and toggle it there first, then this script
# can adjust it afterwards. See docs: src/content/docs/mavlink.md, missions.md.
#
# Usage:
#   ./scripts/configure_mavlink_gcs.sh [device-serial]
#
# Sets, in LyrebirdPrefs.xml:
#   lb_mav_0_enabled       = true        (MAVLink 2 endpoint on)
#   lb_mav_0_allow_flight  = true        (flight motion accepted over MAVLink)
#   lb_mission_exec        = dji_native  (mission survives app backgrounding)

set -euo pipefail

PKG="com.lyrebird.rc"
PREFS_NAME="LyrebirdPrefs"
PREFS_PATH="/data/data/${PKG}/shared_prefs/${PREFS_NAME}.xml"
ADB_SERIAL="${1:-}"

adb_cmd() {
    if [[ -n "$ADB_SERIAL" ]]; then
        adb -s "$ADB_SERIAL" "$@"
    else
        adb "$@"
    fi
}

echo "==> Checking device connection..."
if ! adb_cmd get-state >/dev/null 2>&1; then
    echo "ERROR: no adb device reachable. Connect via USB or 'adb connect <ip>:5555' first." >&2
    exit 1
fi

echo "==> Confirming Lyrebird is installed ($PKG)..."
if ! adb_cmd shell pm list packages "$PKG" | grep -q "$PKG"; then
    echo "ERROR: $PKG is not installed on this device." >&2
    exit 1
fi

echo "==> Checking for an existing prefs file (app must have run at least once)..."
if ! adb_cmd shell "run-as $PKG test -f $PREFS_PATH" 2>/dev/null; then
    cat >&2 <<EOF
ERROR: $PREFS_PATH does not exist yet.

Launch Lyrebird on the device at least once, and turn on "Allow MAVLink flight"
from its in-app menu yourself (it shows a confirmation dialog on purpose -- this
script will not bypass that first-time consent). Then re-run this script to set
the remaining values and verify everything together.
EOF
    exit 1
fi

echo "==> Backing up current prefs to /tmp/lyrebird_prefs_backup.xml..."
adb_cmd shell "run-as $PKG cat $PREFS_PATH" > /tmp/lyrebird_prefs_backup.xml
echo "    Backup saved: /tmp/lyrebird_prefs_backup.xml"

set_bool_pref() {
    local key="$1" value="$2"
    adb_cmd shell "run-as $PKG sh -c '
        if grep -q \"name=\"$key\"\" $PREFS_PATH; then
            sed -i \"s#<boolean name=\"$key\" value=\"[a-z]*\" */>#<boolean name=\"$key\" value=\"$value\" />#\" $PREFS_PATH
        else
            sed -i \"s#</map>#<boolean name=\"$key\" value=\"$value\" /></map>#\" $PREFS_PATH
        fi
    '"
}

set_string_pref() {
    local key="$1" value="$2"
    adb_cmd shell "run-as $PKG sh -c '
        if grep -q \"name=\"$key\"\" $PREFS_PATH; then
            sed -i \"s#<string name=\"$key\">[^<]*</string>#<string name=\"$key\">$value</string>#\" $PREFS_PATH
        else
            sed -i \"s#</map>#<string name=\"$key\">$value</string></map>#\" $PREFS_PATH
        fi
    '"
}

echo "==> Stopping Lyrebird before editing prefs..."
adb_cmd shell am force-stop "$PKG"

echo "==> Setting lb_mav_0_enabled = true"
set_bool_pref "lb_mav_0_enabled" "true"

echo "==> Setting lb_mav_0_allow_flight = true"
set_bool_pref "lb_mav_0_allow_flight" "true"

echo "==> Setting lb_mission_exec = dji_native"
set_string_pref "lb_mission_exec" "dji_native"

echo "==> Verifying..."
adb_cmd shell "run-as $PKG cat $PREFS_PATH" | grep -E "lb_mav_0_enabled|lb_mav_0_allow_flight|lb_mission_exec|lb_mav_0_host|lb_mav_0_port"

echo "==> Relaunching Lyrebird..."
adb_cmd shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null

cat <<'EOF'

Done. Lyrebird's MAVLink 2 endpoint now:
  - broadcasts on UDP 14550 (lb_mav_0_host is left blank -> broadcast/learn-peer mode)
  - accepts flight motion (takeoff/land/RTH/mission) from any MAVLink 2 GCS that talks to it
  - flies uploaded missions on DJI's own wayline engine (dji_native), surviving app
    backgrounding

Next: point UgCS's PX4 VSM at this RC. See
scripts/ugcs/px4_vsm_lyrebird.conf for the matching UgCS-side connection block.

Rollback: restore /tmp/lyrebird_prefs_backup.xml with
  adb shell run-as com.lyrebird.rc sh -c 'cat > PREFS_PATH' < /tmp/lyrebird_prefs_backup.xml
(replace PREFS_PATH with the path printed above; force-stop the app first).
EOF
