#!/usr/bin/env bash
set -euo pipefail

export AGAVE_DB_PATH="${AGAVE_DB_PATH:-/var/data/db/agave_obs.sqlite3}"
export AGAVE_UPLOAD_DIR="${AGAVE_UPLOAD_DIR:-/var/data/uploads/documents}"

mkdir -p "$(dirname "$AGAVE_DB_PATH")" "$AGAVE_UPLOAD_DIR"

if [ ! -f "$AGAVE_DB_PATH" ] && [ -f "data/db/agave_obs.sqlite3" ]; then
  cp "data/db/agave_obs.sqlite3" "$AGAVE_DB_PATH"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8018}"
