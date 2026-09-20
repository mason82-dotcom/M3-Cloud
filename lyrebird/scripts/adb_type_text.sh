#!/usr/bin/env bash
# Type text (e.g. a JSON string) into the currently-focused EditText via
# ADBKeyboard, replacing the field's entire content first.
#
# Requires ADBKeyboard to be installed and active (see setup_adbkeyboard.sh).
# No manual escaping needed: pass the literal text as a single argument.
#
# Usage:
#   ./adb_type_text.sh [device_serial] 'TEXT_TO_TYPE'
#
# Example (NTRIP account JSON for Lyrebird's RTK Center dialog).
# Canonical values for the RC Pro Enterprise (5YSZKAP0020M45) live in
# private-notes/ntrip_rc_pro_enterprise.json (gitignored) — load from there:
#   ./adb_type_text.sh 192.168.178.41:5555 \
#     "$(python3 -c 'import json; d=json.load(open("../private-notes/ntrip_rc_pro_enterprise.json")); d.pop("_comment", None); print(json.dumps(d))')"
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 [device_serial] 'TEXT'" >&2
  exit 1
fi

if [ $# -eq 2 ]; then
  SERIAL="$1"
  TEXT="$2"
else
  SERIAL=""
  TEXT="$1"
fi

ADB_ARGS=()
if [ -n "$SERIAL" ]; then
  ADB_ARGS=(-s "$SERIAL")
fi

B64=$(printf '%s' "$TEXT" | base64 -w0)

echo "Clearing focused field..."
adb "${ADB_ARGS[@]}" shell am broadcast -a ADB_CLEAR_TEXT

echo "Typing text via base64 broadcast..."
adb "${ADB_ARGS[@]}" shell am broadcast -a ADB_INPUT_B64 --es msg "$B64"

echo "Done. Verify with: adb ${ADB_ARGS[*]} shell uiautomator dump /sdcard/verify.xml"
