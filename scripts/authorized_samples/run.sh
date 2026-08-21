#!/usr/bin/env bash
set -Eeuo pipefail

# Import the pinned public real-origin sample into a persistent, private local
# RustFS bucket. Credentials and object bytes stay in ignored runtime paths.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUSTFS_DIR="$ROOT_DIR/infra/rustfs"
RUNTIME_DIR="$RUSTFS_DIR/.runtime"
ENV_FILE="$RUNTIME_DIR/authorized-fixtures.env"
COMPOSE_FILE="$RUSTFS_DIR/authorized-fixtures-compose.yaml"

case "$RUNTIME_DIR" in
  "$ROOT_DIR"/infra/rustfs/.runtime) ;;
  *) echo "refusing unexpected runtime path: $RUNTIME_DIR" >&2; exit 2 ;;
esac

mkdir -p "$RUNTIME_DIR/authorized-data" "$RUNTIME_DIR/authorized-logs"
if [[ ! -f "$ENV_FILE" ]]; then
  umask 077
  python - "$ENV_FILE" <<'PY'
import base64
import secrets
import sys
from pathlib import Path

target = Path(sys.argv[1])
values = {
    "RUSTFS_ACCESS_KEY": "ccf" + secrets.token_hex(24),
    "RUSTFS_SECRET_KEY": "ccf" + secrets.token_hex(24),
    "RUSTFS_RPC_SECRET": "ccf-rpc-" + secrets.token_hex(24),
    "RUSTFS_SSE_S3_MASTER_KEY": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
}
target.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
PY
  chmod 600 "$ENV_FILE"
fi

# Let Compose read the env file directly. In Git Bash an exported Base64 value
# beginning with `/` can be rewritten as an MSYS path before docker.exe sees
# it, which corrupts the SSE master key.
env \
  -u RUSTFS_ACCESS_KEY \
  -u RUSTFS_SECRET_KEY \
  -u RUSTFS_RPC_SECRET \
  -u RUSTFS_SSE_S3_MASTER_KEY \
  docker compose \
  --project-name crash-cap-authorized-fixtures \
  --env-file "$ENV_FILE" \
  --file "$COMPOSE_FILE" \
  up -d --force-recreate rustfs

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

VENV_DIR="$RUNTIME_DIR/.venv"
if [[ ! -x "$VENV_DIR/Scripts/python.exe" && ! -x "$VENV_DIR/bin/python" ]]; then
  python -m venv "$VENV_DIR"
fi
if [[ -x "$VENV_DIR/Scripts/python.exe" ]]; then
  VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
else
  VENV_PYTHON="$VENV_DIR/bin/python"
fi
"$VENV_PYTHON" -m pip install --disable-pip-version-check --quiet \
  -r "$ROOT_DIR/qualification/s3/requirements.txt"

export S3_ENDPOINT="http://127.0.0.1:9002"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ROOT_DIR" \
  "$VENV_PYTHON" "$ROOT_DIR/scripts/authorized_samples/import_rust_minidump.py"
