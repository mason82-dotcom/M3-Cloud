#!/usr/bin/env bash
# One-time setup: install and activate ADBKeyBoard on a connected Android
# device (the DJI RC Pro Enterprise in our case), so that adb-driven text
# entry (NTRIP JSON, etc.) is reliable instead of relying on `input text`
# char-by-char escaping + blind backspace loops.
#
# Usage: ./setup_adbkeyboard.sh [device_serial]
set -euo pipefail

SERIAL="${1:-}"
APK=/tmp/ADBKeyboard.apk

if [ ! -f "$APK" ]; then
  echo "Downloading ADBKeyboard APK..."
  curl -sL -o "$APK" "https://github.com/senzhk/ADBKeyBoard/releases/download/v2.4-dev/keyboardservice-debug.apk"
fi

ADB_ARGS=()
if [ -n "$SERIAL" ]; then
  ADB_ARGS=(-s "$SERIAL")
fi

echo "Installing ADBKeyboard..."
adb "${ADB_ARGS[@]}" install -r "$APK"

echo "Activating ADBKeyboard as the input method..."
adb "${ADB_ARGS[@]}" shell ime enable com.android.adbkeyboard/.AdbIME
adb "${ADB_ARGS[@]}" shell ime set com.android.adbkeyboard/.AdbIME

echo "Current IME:"
adb "${ADB_ARGS[@]}" shell settings get secure default_input_method

echo "Done. Use adb_type_text.sh to type text/JSON into the focused field."
