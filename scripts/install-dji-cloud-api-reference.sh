#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${1:-.vendor/dji-cloud-api}"
INCLUDE_DEMO="${DJI_CLOUD_API_INCLUDE_DEPRECATED_DEMO:-0}"
FORCE_REFRESH="${DJI_CLOUD_API_FORCE_REFRESH:-0}"

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 1; }

sync_repo() {
  local url="$1"
  local dest="$2"
  local ref="$3"

  if [[ -d "$dest/.git" ]]; then
    if [[ "$FORCE_REFRESH" != "1" ]]; then
      echo "Already installed: $dest"
      return
    fi
    git -C "$dest" fetch --prune origin
    git -C "$dest" checkout "$ref"
    git -C "$dest" pull --ff-only origin "$ref"
    return
  fi

  if [[ -e "$dest" ]]; then
    echo "Destination exists but is not a Git repository: $dest" >&2
    exit 1
  fi

  mkdir -p "$(dirname "$dest")"
  git clone --branch "$ref" --single-branch "$url" "$dest"
}

mkdir -p "$INSTALL_ROOT"

cat <<'EOF'
DJI Cloud API
=============
The official DJI product page currently reports Cloud API 1.14.0.
Cloud API is a protocol/server integration (MQTT + HTTPS + WebSocket), not a
Gradle/Python package. M3-Cloud already implements the production server path;
this installer adds DJI's official public reference sources.
EOF

DOC_DIR="$INSTALL_ROOT/Cloud-API-Doc"
sync_repo "https://github.com/dji-sdk/Cloud-API-Doc.git" "$DOC_DIR" master

echo
echo "Installed documentation mirror:"
echo "  path:   $DOC_DIR"
echo "  commit: $(git -C "$DOC_DIR" rev-parse HEAD)"
echo "  note:   $(git -C "$DOC_DIR" log -1 --pretty=%s)"
echo "WARNING: DJI's public Cloud-API-Doc GitHub mirror can lag behind developer.dji.com."
echo "Treat https://developer.dji.com/cloud-api/ as authoritative for the current version."

if [[ "$INCLUDE_DEMO" == "1" ]]; then
  echo "WARNING: DJI ended maintenance of the Cloud API demo on 2025-04-10."
  sync_repo "https://github.com/dji-sdk/DJI-Cloud-API-Demo.git" "$INSTALL_ROOT/DJI-Cloud-API-Demo" master
  sync_repo "https://github.com/dji-sdk/Cloud-API-Demo-Web.git" "$INSTALL_ROOT/Cloud-API-Demo-Web" master
fi

cat <<'EOF'

M3-Cloud integration:
  production backend: backend/app/dji/
  Pilot 2 bootstrap:  /api/v1/dji/pilot/bootstrap
  Pilot 2 status:     /api/v1/dji/pilot/status
  setup guide:        docs/dji-cloud-api.md

Done.
EOF
