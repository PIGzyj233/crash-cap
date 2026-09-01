#!/usr/bin/env bash
set -Eeuo pipefail

# Build and start the Crash-Cap Phase 1 stack on one Linux Docker host.
# Secrets are generated outside the repository, never printed, and reused on
# subsequent runs. This script deliberately never removes Docker volumes.

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  bash ./scripts/phase1/deploy_linux.sh

The first run generates mode-0600 secrets under:
  ${XDG_STATE_HOME:-$HOME/.local/state}/crash-cap

Common overrides:
  CRASHCAP_EXTERNAL_BIND_HOST=10.20.30.40   Approved private IPv4; default 127.0.0.1
  CRASHCAP_DEPLOY_STATE_DIR=/secure/path    Secret/runtime directory outside the repo
  PHASE1_API_PORT=8080
  PHASE1_WEB_PORT=30080
  PHASE1_S3_GATEWAY_PORT=59000
  PHASE1_METRICS_PORT=9108
  CRASHCAP_START_TIMEOUT_SECONDS=300
  CRASHCAP_BUILD_PULL=1                     Set to 0 to avoid refreshing build bases

Linux prerequisites include the getfacl/setfacl commands from the `acl` package.
The deployer grants only RustFS runtime UID 10001 read ACLs on its three secret
files; PostgreSQL, Redis and runtime-env files remain mode 0600.

Operator-managed secret files may be supplied with the PHASE1_*_FILE variables
documented in docs/operations/phase1-deployment.md. Explicit files must already
exist, be outside the repository, and have no access beyond the owner and the
expected RustFS UID ACL described above.

The script is idempotent for upgrades. It builds current source and runs
`docker compose up -d`; it never invokes `down -v`, `volume rm`, or data reset.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
[[ "$#" -eq 0 ]] || die "unknown argument: $1 (use --help)"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "$script_dir/../.." && pwd -P)
compose_file="$repo_root/deploy/compose/phase1.yml"

[[ "$(uname -s)" == "Linux" ]] || die "this entrypoint supports Linux only"
case "$(uname -m)" in
  x86_64|amd64) ;;
  *) die "only Linux x86_64 is currently supported by the pinned deployment images" ;;
esac

for required_command in docker curl getfacl openssl realpath setfacl stat; do
  command -v "$required_command" >/dev/null 2>&1 || die "$required_command is required"
done
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 (docker compose) is required"
docker info >/dev/null 2>&1 || die "cannot access the Docker daemon"
[[ "$(docker info --format '{{.OSType}}')" == "linux" ]] || die "Docker Engine must run Linux containers"
[[ -f "$compose_file" ]] || die "Compose file not found: $compose_file"

if [[ -n "${CRASHCAP_DEPLOY_STATE_DIR:-}" ]]; then
  deploy_state_dir=$CRASHCAP_DEPLOY_STATE_DIR
else
  [[ -n "${HOME:-}" ]] || die "HOME is required when CRASHCAP_DEPLOY_STATE_DIR is unset"
  deploy_state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/crash-cap"
fi
mkdir -p -- "$deploy_state_dir"
chmod 0700 "$deploy_state_dir"
deploy_state_dir=$(realpath -e -- "$deploy_state_dir")
case "$deploy_state_dir" in
  "$repo_root"|"$repo_root"/*) die "CRASHCAP_DEPLOY_STATE_DIR must be outside the repository" ;;
esac

docker_endpoint=${DOCKER_HOST:-}
if [[ -z "$docker_endpoint" ]]; then
  docker_endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)
fi
if [[ -n "${DOCKER_SOCKET_PATH:-}" ]]; then
  docker_socket_path=$DOCKER_SOCKET_PATH
else
  case "$docker_endpoint" in
    unix://*) docker_socket_path=${docker_endpoint#unix://} ;;
    "") docker_socket_path=/var/run/docker.sock ;;
    *) die "the Worker requires a local Unix Docker socket; remote Docker endpoint is unsupported" ;;
  esac
fi
[[ -S "$docker_socket_path" ]] || die "Docker socket not found: $docker_socket_path"
docker_socket_path=$(realpath -e -- "$docker_socket_path")
export DOCKER_SOCKET_PATH=$docker_socket_path
export DOCKER_GID=${DOCKER_GID:-$(stat -Lc '%g' "$docker_socket_path")}
[[ "$DOCKER_GID" =~ ^[0-9]+$ ]] || die "DOCKER_GID must be numeric"

# The pinned RustFS image and the Worker image used by storage-init both run as
# UID 10001. Docker Compose implements file-backed secrets as bind mounts, so
# service-level uid/gid/mode declarations cannot remap a mode-0600 host file.
# Grant only that numeric runtime UID a read ACL while preserving deployment-
# account ownership and denying the owning group and everyone else.
rustfs_secret_reader_uid=10001

assert_outside_repo() {
  local file_path=$1
  local resolved_path
  resolved_path=$(realpath -e -- "$file_path")
  case "$resolved_path" in
    "$repo_root"|"$repo_root"/*) die "secret/runtime file must be outside the repository: $resolved_path" ;;
  esac
}

assert_private_file() {
  local file_path=$1
  local file_mode permission_value
  [[ -f "$file_path" && -r "$file_path" ]] || die "required file is not readable: $file_path"
  assert_outside_repo "$file_path"
  file_mode=$(stat -Lc '%a' "$file_path")
  permission_value=$((8#$file_mode))
  (( (permission_value & 077) == 0 )) || die "file must not grant group/other permissions: $file_path"
}

inspect_rustfs_secret_acl() {
  local file_path=$1
  local reader_uid=$2
  local acl_output acl_line
  local owner_entries=0 reader_entries=0 group_entries=0 mask_entries=0 other_entries=0

  [[ -f "$file_path" && -r "$file_path" ]] || die "required file is not readable: $file_path"
  assert_outside_repo "$file_path"
  acl_output=$(getfacl -cpn -- "$file_path") || die "cannot inspect secret ACL: $file_path"
  while IFS= read -r acl_line; do
    [[ -z "$acl_line" ]] && continue
    case "$acl_line" in
      user::r--|user::rw-) owner_entries=$((owner_entries + 1)) ;;
      user:"$reader_uid":r--) reader_entries=$((reader_entries + 1)) ;;
      group::---) group_entries=$((group_entries + 1)) ;;
      mask::r--) mask_entries=$((mask_entries + 1)) ;;
      other::---) other_entries=$((other_entries + 1)) ;;
      *) die "secret has an unexpected ACL entry ($acl_line): $file_path" ;;
    esac
  done <<< "$acl_output"

  (( owner_entries == 1 )) || die "secret owner ACL must grant read access only: $file_path"
  (( group_entries == 1 )) || die "secret owning-group ACL must be empty: $file_path"
  (( other_entries == 1 )) || die "secret other-user ACL must be empty: $file_path"
  (( reader_entries <= 1 )) || die "secret has duplicate RustFS reader ACL entries: $file_path"
  if (( reader_entries == 1 )); then
    (( mask_entries == 1 )) || die "secret RustFS reader ACL requires a read-only mask: $file_path"
  else
    (( mask_entries == 0 )) || die "secret ACL mask exists without the RustFS reader: $file_path"
  fi

  rustfs_secret_owner_uid=$(stat -Lc '%u' "$file_path")
  rustfs_secret_reader_acl_present=$reader_entries
}

ensure_rustfs_secret_reader() {
  local file_path=$1
  local reader_uid=$2

  inspect_rustfs_secret_acl "$file_path" "$reader_uid"
  if [[ "$rustfs_secret_owner_uid" != "$reader_uid" ]] && (( rustfs_secret_reader_acl_present == 0 )); then
    setfacl -m "u:${reader_uid}:r--,m::r--" -- "$file_path" \
      || die "cannot grant the RustFS runtime UID read access to secret: $file_path"
    inspect_rustfs_secret_acl "$file_path" "$reader_uid"
  fi
  if [[ "$rustfs_secret_owner_uid" != "$reader_uid" ]]; then
    (( rustfs_secret_reader_acl_present == 1 )) \
      || die "secret is not readable by RustFS runtime UID $reader_uid: $file_path"
  fi
}

read_secret() {
  local file_path=$1
  local secret_value
  secret_value=$(tr -d '\r\n' < "$file_path")
  [[ -n "$secret_value" ]] || die "secret file is empty: $file_path"
  printf '%s' "$secret_value"
}

generate_secret() {
  local file_path=$1
  local secret_kind=$2
  local temp_file
  temp_file=$(mktemp "${file_path}.tmp.XXXXXX")
  chmod 0600 "$temp_file"
  case "$secret_kind" in
    password) openssl rand -hex 24 > "$temp_file" ;;
    access-key) printf 'cc%s\n' "$(openssl rand -hex 12)" > "$temp_file" ;;
    secret-key) openssl rand -hex 32 > "$temp_file" ;;
    sse-master-key) openssl rand -base64 32 | tr -d '\n' > "$temp_file"; printf '\n' >> "$temp_file" ;;
    *) rm -f -- "$temp_file"; die "unknown secret kind: $secret_kind" ;;
  esac
  mv -- "$temp_file" "$file_path"
  chmod 0600 "$file_path"
}

managed_secret() {
  local variable_name=$1
  local default_name=$2
  local secret_kind=$3
  local protected_volume=$4
  local reader_uid=${5:-}
  local explicit_path file_path
  explicit_path=${!variable_name:-}
  if [[ -n "$explicit_path" ]]; then
    [[ -f "$explicit_path" ]] || die "$variable_name points to a missing operator-managed file"
    file_path=$(realpath -e -- "$explicit_path")
  else
    file_path="$deploy_state_dir/$default_name"
    if [[ ! -f "$file_path" ]]; then
      if docker volume inspect "$protected_volume" >/dev/null 2>&1; then
        die "$file_path is missing but data volume $protected_volume exists; restore the original secret or remove the volume explicitly"
      fi
      generate_secret "$file_path" "$secret_kind"
    fi
  fi
  if [[ -n "$reader_uid" ]]; then
    ensure_rustfs_secret_reader "$file_path" "$reader_uid"
  else
    assert_private_file "$file_path"
  fi
  printf -v "$variable_name" '%s' "$file_path"
  export "${variable_name?}"
}

postgres_volume=${PHASE1_POSTGRES_VOLUME:-crashcap_phase1_postgres}
redis_volume=${PHASE1_REDIS_VOLUME:-crashcap_phase1_redis}
rustfs_volume=${PHASE1_RUSTFS_VOLUME:-crashcap_phase1_rustfs}

managed_secret PHASE1_POSTGRES_PASSWORD_FILE postgres_password password "$postgres_volume"
managed_secret PHASE1_REDIS_PASSWORD_FILE redis_password password "$redis_volume"
managed_secret \
  PHASE1_RUSTFS_ACCESS_KEY_FILE rustfs_access_key access-key \
  "$rustfs_volume" "$rustfs_secret_reader_uid"
managed_secret \
  PHASE1_RUSTFS_SECRET_KEY_FILE rustfs_secret_key secret-key \
  "$rustfs_volume" "$rustfs_secret_reader_uid"
managed_secret \
  PHASE1_RUSTFS_SSE_MASTER_KEY_FILE rustfs_sse_s3_master_key sse-master-key \
  "$rustfs_volume" "$rustfs_secret_reader_uid"

urlencode() {
  local input=$1
  local output="" character hex index
  local LC_ALL=C
  for ((index = 0; index < ${#input}; index++)); do
    character=${input:index:1}
    case "$character" in
      [a-zA-Z0-9.~_-]) output+=$character ;;
      *)
        printf -v hex '%02X' "'$character"
        output+="%$hex"
        ;;
    esac
  done
  printf '%s' "$output"
}

if [[ -n "${PHASE1_RUNTIME_ENV_FILE:-}" ]]; then
  [[ -f "$PHASE1_RUNTIME_ENV_FILE" ]] || die "PHASE1_RUNTIME_ENV_FILE points to a missing operator-managed file"
  PHASE1_RUNTIME_ENV_FILE=$(realpath -e -- "$PHASE1_RUNTIME_ENV_FILE")
  assert_private_file "$PHASE1_RUNTIME_ENV_FILE"
else
  PHASE1_RUNTIME_ENV_FILE="$deploy_state_dir/runtime.env"
  postgres_password=$(read_secret "$PHASE1_POSTGRES_PASSWORD_FILE")
  redis_password=$(read_secret "$PHASE1_REDIS_PASSWORD_FILE")
  rustfs_access_key=$(read_secret "$PHASE1_RUSTFS_ACCESS_KEY_FILE")
  rustfs_secret_key=$(read_secret "$PHASE1_RUSTFS_SECRET_KEY_FILE")
  [[ "$rustfs_access_key" =~ ^[a-zA-Z0-9.~_-]+$ ]] || die "generated RustFS access key is not env-file safe"
  [[ "$rustfs_secret_key" =~ ^[a-zA-Z0-9.~_-]+$ ]] || die "generated RustFS secret key is not env-file safe"
  runtime_temp=$(mktemp "$deploy_state_dir/runtime.env.tmp.XXXXXX")
  chmod 0600 "$runtime_temp"
  {
    printf 'CRASHCAP_DATABASE_URL=postgresql+psycopg://crashcap:%s@postgres:5432/crashcap\n' "$(urlencode "$postgres_password")"
    printf 'CRASHCAP_REDIS_URL=redis://:%s@redis:6379/0\n' "$(urlencode "$redis_password")"
    printf 'CRASHCAP_S3_ACCESS_KEY=%s\n' "$rustfs_access_key"
    printf 'CRASHCAP_S3_SECRET_KEY=%s\n' "$rustfs_secret_key"
  } > "$runtime_temp"
  mv -- "$runtime_temp" "$PHASE1_RUNTIME_ENV_FILE"
  chmod 0600 "$PHASE1_RUNTIME_ENV_FILE"
  unset postgres_password redis_password rustfs_access_key rustfs_secret_key
fi
export PHASE1_RUNTIME_ENV_FILE

validate_runtime_env_keys() {
  local file_path=$1
  local invalid=0
  local key raw_line
  local -A found=()
  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    [[ "$raw_line" =~ ^[[:space:]]*$ || "$raw_line" =~ ^[[:space:]]*# ]] && continue
    if [[ "$raw_line" != *"="* ]]; then
      invalid=1
      continue
    fi
    key=${raw_line%%=*}
    key=${key//[[:space:]]/}
    if [[ "$key" =~ ^CRASHCAP_[A-Z0-9_]+$ && -z "${found[$key]:-}" ]]; then
      found["$key"]=1
    else
      invalid=1
    fi
  done < "$file_path"
  (( invalid == 0 )) || die "runtime env must contain only KEY=VALUE CRASHCAP_* entries"
  for key in CRASHCAP_DATABASE_URL CRASHCAP_REDIS_URL CRASHCAP_S3_ACCESS_KEY CRASHCAP_S3_SECRET_KEY; do
    [[ -n "${found[$key]:-}" ]] || die "runtime env is missing required key: $key"
  done
}
validate_runtime_env_keys "$PHASE1_RUNTIME_ENV_FILE"

export COMPOSE_PROJECT_NAME=crash-cap-phase1
export CRASHCAP_EXTERNAL_BIND_HOST=${CRASHCAP_EXTERNAL_BIND_HOST:-127.0.0.1}
[[ "$CRASHCAP_EXTERNAL_BIND_HOST" != *:* ]] || die "deploy_linux.sh currently requires an IPv4 bind address"
export PHASE1_API_PORT=${PHASE1_API_PORT:-8080}
export PHASE1_WEB_PORT=${PHASE1_WEB_PORT:-30080}
export PHASE1_S3_GATEWAY_PORT=${PHASE1_S3_GATEWAY_PORT:-59000}
export PHASE1_METRICS_PORT=${PHASE1_METRICS_PORT:-9108}
for port_variable in PHASE1_API_PORT PHASE1_WEB_PORT PHASE1_S3_GATEWAY_PORT PHASE1_METRICS_PORT; do
  port_value=${!port_variable}
  if [[ ! "$port_value" =~ ^[0-9]+$ ]] || (( port_value < 1 || port_value > 65535 )); then
    die "$port_variable must be a TCP port from 1 to 65535"
  fi
done
export CRASHCAP_S3_PUBLIC_ENDPOINT_URL=${CRASHCAP_S3_PUBLIC_ENDPOINT_URL:-http://$CRASHCAP_EXTERNAL_BIND_HOST:$PHASE1_S3_GATEWAY_PORT}
export S3_CORS_ALLOWED_ORIGINS=${S3_CORS_ALLOWED_ORIGINS:-http://$CRASHCAP_EXTERNAL_BIND_HOST:$PHASE1_WEB_PORT}
export CRASHCAP_TRUSTED_INTRANET_ACKNOWLEDGED=true
export CRASHCAP_CORE_IMAGE=${CRASHCAP_CORE_IMAGE:-crash-cap/dmp-core:phase1}
start_timeout=${CRASHCAP_START_TIMEOUT_SECONDS:-300}
if [[ ! "$start_timeout" =~ ^[0-9]+$ ]] || (( start_timeout < 30 )); then
  die "CRASHCAP_START_TIMEOUT_SECONDS must be an integer of at least 30"
fi

compose() {
  docker compose --project-name "$COMPOSE_PROJECT_NAME" --file "$compose_file" "$@"
}

build_flags=()
if [[ "${CRASHCAP_BUILD_PULL:-1}" == "1" ]]; then
  build_flags+=(--pull)
elif [[ "${CRASHCAP_BUILD_PULL}" != "0" ]]; then
  die "CRASHCAP_BUILD_PULL must be 0 or 1"
fi

printf 'Building dmp-core from current checkout...\n'
docker build "${build_flags[@]}" --file "$repo_root/deploy/core/Dockerfile" --tag "$CRASHCAP_CORE_IMAGE" "$repo_root"
export CRASHCAP_CORE_IMAGE_DIGEST
CRASHCAP_CORE_IMAGE_DIGEST=$(docker image inspect --format '{{.Id}}' "$CRASHCAP_CORE_IMAGE")
[[ "$CRASHCAP_CORE_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || die "could not resolve the local dmp-core OCI image ID"

printf 'Validating Compose interpolation...\n'
compose config --quiet

printf 'Building application images...\n'
compose build "${build_flags[@]}" api worker frontend s3-gateway symbolicator-gateway ops-exporter

gate_runtime_file=$(mktemp "${TMPDIR:-/tmp}/crash-cap-runtime-keys.XXXXXX")
chmod 0644 "$gate_runtime_file"
cat > "$gate_runtime_file" <<'EOF'
CRASHCAP_DATABASE_URL=redacted
CRASHCAP_REDIS_URL=redacted
CRASHCAP_S3_ACCESS_KEY=redacted
CRASHCAP_S3_SECRET_KEY=redacted
EOF
cleanup_gate_file() { rm -f -- "$gate_runtime_file"; }
trap cleanup_gate_file EXIT

printf 'Running the static deployment gate...\n'
docker run --rm --network none --read-only --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
  --volume "$repo_root:/workspace:ro" \
  --volume "$gate_runtime_file:/runtime.env:ro" \
  --env CRASHCAP_EXTERNAL_BIND_HOST \
  --env PHASE1_API_PORT \
  --env PHASE1_WEB_PORT \
  --env PHASE1_S3_GATEWAY_PORT \
  --env PHASE1_METRICS_PORT \
  --env CRASHCAP_S3_PUBLIC_ENDPOINT_URL \
  --env S3_CORS_ALLOWED_ORIGINS \
  --env CRASHCAP_TRUSTED_INTRANET_ACKNOWLEDGED \
  --env CRASHCAP_CORE_IMAGE \
  --env CRASHCAP_CORE_IMAGE_DIGEST \
  --workdir /workspace \
  --entrypoint python \
  crash-cap/worker:phase1 \
  /workspace/scripts/phase1/deploy_check.py \
  --runtime-env-file /runtime.env
rm -f -- "$gate_runtime_file"
trap - EXIT

if [[ "${CRASHCAP_PULL_EXTERNAL_IMAGES:-1}" == "1" ]]; then
  printf 'Pulling pinned/external service images...\n'
  compose pull postgres redis rustfs symbolicator otel-collector
elif [[ "${CRASHCAP_PULL_EXTERNAL_IMAGES}" != "0" ]]; then
  die "CRASHCAP_PULL_EXTERNAL_IMAGES must be 0 or 1"
fi

printf 'Verifying RustFS secret mounts as runtime UID %s...\n' "$rustfs_secret_reader_uid"
compose run --rm --no-deps --entrypoint /bin/sh rustfs -ec '
  actual_uid="$(id -u)"
  if [ "$actual_uid" != "10001" ]; then
    echo "ERROR: RustFS runtime UID changed from the reviewed value: $actual_uid" >&2
    exit 1
  fi
  for secret_path in \
    /run/secrets/rustfs_access_key \
    /run/secrets/rustfs_secret_key \
    /run/secrets/rustfs_sse_s3_master_key
  do
    if [ ! -r "$secret_path" ]; then
      echo "ERROR: RustFS runtime user cannot read secret: $secret_path" >&2
      exit 1
    fi
  done
' || die "RustFS runtime secret-mount preflight failed"

printf 'Verifying storage-init secret mounts as runtime UID %s...\n' "$rustfs_secret_reader_uid"
compose run --rm --no-deps --entrypoint /bin/sh storage-init -ec '
  actual_uid="$(id -u)"
  if [ "$actual_uid" != "10001" ]; then
    echo "ERROR: storage-init runtime UID changed from the reviewed value: $actual_uid" >&2
    exit 1
  fi
  for secret_path in \
    /run/secrets/rustfs_access_key \
    /run/secrets/rustfs_secret_key
  do
    if [ ! -r "$secret_path" ]; then
      echo "ERROR: storage-init runtime user cannot read secret: $secret_path" >&2
      exit 1
    fi
  done
' || die "storage-init runtime secret-mount preflight failed"

printf 'Starting Crash-Cap services...\n'
compose up -d --remove-orphans

deadline=$((SECONDS + start_timeout))

wait_for_service() {
  local service_name=$1
  local container_id state health
  while (( SECONDS < deadline )); do
    container_id=$(compose ps --all --quiet "$service_name" 2>/dev/null || true)
    if [[ -n "$container_id" ]]; then
      state=$(docker inspect --format '{{.State.Status}}' "$container_id")
      health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")
      if [[ "$state" == "running" && ( "$health" == "healthy" || "$health" == "none" ) ]]; then
        return 0
      fi
      [[ "$state" != "exited" && "$state" != "dead" ]] || die "$service_name stopped before becoming ready"
    fi
    sleep 2
  done
  die "timed out waiting for service: $service_name"
}

require_init_success() {
  local service_name=$1
  local container_id state exit_code
  container_id=$(compose ps --all --quiet "$service_name" 2>/dev/null || true)
  [[ -n "$container_id" ]] || die "initialization container is missing: $service_name"
  state=$(docker inspect --format '{{.State.Status}}' "$container_id")
  exit_code=$(docker inspect --format '{{.State.ExitCode}}' "$container_id")
  [[ "$state" == "exited" && "$exit_code" == "0" ]] || die "$service_name did not complete successfully"
}

require_init_success symbols-init
require_init_success storage-init
require_init_success migrate
for service_name in postgres redis rustfs s3-gateway symbolicator symbolicator-gateway api worker worker-verify worker-ingest worker-dump-large otel-collector ops-docker-proxy ops-exporter retention frontend; do
  wait_for_service "$service_name"
done

wait_for_http() {
  local endpoint_name=$1
  local endpoint_url=$2
  while (( SECONDS < deadline )); do
    if curl --fail --silent --show-error --connect-timeout 2 --max-time 5 --output /dev/null "$endpoint_url"; then
      printf '%s ready: %s\n' "$endpoint_name" "$endpoint_url"
      return 0
    fi
    sleep 2
  done
  die "timed out waiting for $endpoint_name at $endpoint_url"
}

api_url="http://$CRASHCAP_EXTERNAL_BIND_HOST:$PHASE1_API_PORT"
frontend_url="http://$CRASHCAP_EXTERNAL_BIND_HOST:$PHASE1_WEB_PORT"
s3_gateway_url="http://$CRASHCAP_EXTERNAL_BIND_HOST:$PHASE1_S3_GATEWAY_PORT"
metrics_url="http://$CRASHCAP_EXTERNAL_BIND_HOST:$PHASE1_METRICS_PORT"

wait_for_http API "$api_url/readyz"
wait_for_http "S3 Gateway" "$s3_gateway_url/health/ready"
wait_for_http Metrics "$metrics_url/healthz"

if ! curl --fail --silent --connect-timeout 2 --max-time 5 --output /dev/null "$frontend_url/healthz"; then
  printf 'Frontend is not ready after API recreation; restarting its stateless Nginx container...\n'
  compose restart frontend
  wait_for_service frontend
fi
wait_for_http Frontend "$frontend_url/healthz"

compose ps --all
printf '\nCrash-Cap is ready.\n'
printf 'Frontend:  %s\n' "$frontend_url"
printf 'API:       %s\n' "$api_url"
printf 'S3 gateway:%s\n' " $s3_gateway_url"
printf 'Metrics:   %s\n' "$metrics_url"
printf 'Secrets:   %s (not printed; preserve this directory with backups)\n' "$deploy_state_dir"
