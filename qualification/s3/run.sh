#!/usr/bin/env bash
set -Eeuo pipefail

# This script is intentionally non-destructive outside the disposable
# infra/rustfs/.runtime directory. It generates credentials in memory and in a
# mode-0600 temporary env file; neither is printed or written to the repository.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUSTFS_DIR="$ROOT_DIR/infra/rustfs"
RUNTIME_DIR="$RUSTFS_DIR/.runtime"
COMPOSE_FILE="$RUSTFS_DIR/compose.yaml"
ENV_FILE=""
KEEP_RUSTFS="${KEEP_RUSTFS:-0}"

case "$RUNTIME_DIR" in
  "$ROOT_DIR"/infra/rustfs/.runtime) ;;
  *) echo "refusing unexpected runtime path: $RUNTIME_DIR" >&2; exit 2 ;;
esac

mkdir -p "$RUNTIME_DIR"
rm -rf -- "$RUNTIME_DIR/data" "$RUNTIME_DIR/logs" "$RUNTIME_DIR/backup" "$RUNTIME_DIR/tls"
mkdir -p "$RUNTIME_DIR/data" "$RUNTIME_DIR/logs" "$RUNTIME_DIR/tls"

# Generate a short-lived, qualification-only certificate. The private key and
# CA never enter the repository, and the SAN forces real hostname verification
# for the loopback S3 endpoint rather than an insecure TLS bypass.
MSYS2_ARG_CONV_EXCL='/CN=' openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 2 \
  -subj "/CN=127.0.0.1" \
  -addext "subjectAltName=IP:127.0.0.1,DNS:localhost" \
  -keyout "$RUNTIME_DIR/tls/rustfs_key.pem" \
  -out "$RUNTIME_DIR/tls/rustfs_cert.pem" >/dev/null 2>&1
cp "$RUNTIME_DIR/tls/rustfs_cert.pem" "$RUNTIME_DIR/tls/ca.crt"
chmod 0644 "$RUNTIME_DIR/tls/rustfs_key.pem" "$RUNTIME_DIR/tls/rustfs_cert.pem" "$RUNTIME_DIR/tls/ca.crt"

random_hex() {
  python -c 'import secrets; print(secrets.token_hex(24))'
}

export RUSTFS_ACCESS_KEY="ccq$(random_hex)"
export RUSTFS_SECRET_KEY="ccq$(random_hex)"
export RUSTFS_RPC_SECRET="ccq-rpc-$(random_hex)"
export RUSTFS_SSE_S3_MASTER_KEY="$(python -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())')"
export RUSTFS_EXPECTED_DIGEST="sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332965ae0c55fe8b3afed89c831"
export RUSTFS_IMAGE_REF="ghcr.io/rustfs/rustfs:1.0.0-rc.2-glibc@${RUSTFS_EXPECTED_DIGEST}"
export S3_ENDPOINT="https://127.0.0.1:9000"
export S3_CA_BUNDLE="$RUNTIME_DIR/tls/ca.crt"

umask 077
ENV_FILE="$(mktemp "${TMPDIR:-/tmp}/crash-cap-rustfs.XXXXXX.env")"
{
  printf 'RUSTFS_ACCESS_KEY=%s\n' "$RUSTFS_ACCESS_KEY"
  printf 'RUSTFS_SECRET_KEY=%s\n' "$RUSTFS_SECRET_KEY"
  printf 'RUSTFS_RPC_SECRET=%s\n' "$RUSTFS_RPC_SECRET"
  printf 'RUSTFS_SSE_S3_MASTER_KEY=%s\n' "$RUSTFS_SSE_S3_MASTER_KEY"
} > "$ENV_FILE"

compose() {
  docker compose \
    --project-name crash-cap-rustfs-qualification \
    --env-file "$ENV_FILE" \
    --file "$COMPOSE_FILE" "$@"
}

cleanup() {
  local result=$?
  if [[ "$KEEP_RUSTFS" != "1" ]]; then
    compose down --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -f -- "$ENV_FILE"
  return "$result"
}
trap cleanup EXIT

compose down --remove-orphans >/dev/null 2>&1 || true
compose up -d rustfs

VENV_DIR="$RUNTIME_DIR/.venv"
if [[ ! -x "$VENV_DIR/Scripts/python.exe" && ! -x "$VENV_DIR/bin/python" ]]; then
  python -m venv "$VENV_DIR"
fi
if [[ -x "$VENV_DIR/Scripts/python.exe" ]]; then
  VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
else
  VENV_PYTHON="$VENV_DIR/bin/python"
fi
"$VENV_PYTHON" -m pip install --disable-pip-version-check --quiet -r "$ROOT_DIR/qualification/s3/requirements.txt"

set +e
PYTHONPATH="$ROOT_DIR" "$VENV_PYTHON" -m qualification.s3.runner
RESULT=$?
set -e

exit "$RESULT"
