#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${PYTHON_BIN:-python3}"

python_version="$("$python_bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$python_version" != "3.12" ]]; then
  echo "Python 3.12 is required to regenerate backend lockfiles (found $python_version)." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to regenerate frontend/package-lock.json." >&2
  exit 1
fi

node_major="$(node -p 'process.versions.node.split(".")[0]')"
if [[ "$node_major" != "22" ]]; then
  echo "Node.js 22 is required to regenerate the frontend lockfile (found major $node_major)." >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

"$python_bin" -m venv "$tmp_dir/venv"
lock_python="$tmp_dir/venv/bin/python"

"$lock_python" -m pip install --disable-pip-version-check "pip==25.2" "pip-tools==7.5.1"

"$lock_python" -m piptools compile \
  --generate-hashes \
  --resolver=backtracking \
  --output-file=backend/requirements.lock \
  backend/requirements.in

"$lock_python" -m piptools compile \
  --generate-hashes \
  --resolver=backtracking \
  --output-file=backend/requirements-dev.lock \
  backend/requirements-dev.in

(
  cd frontend
  npm install --package-lock-only --ignore-scripts --no-audit --no-fund
)

echo "Updated backend/requirements*.lock and frontend/package-lock.json."
