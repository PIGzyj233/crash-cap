#!/usr/bin/env python3
"""Static security and topology gate for the Phase 1 Compose file.

This checker intentionally does not run containers and never prints resolved
environment values.  It is safe to run in CI and on an operator workstation.
The Compose file still requires secret files outside the repository; use an
external env file only when actually starting the stack.
"""

from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised on minimal hosts
    raise SystemExit("deploy_check.py requires PyYAML (python -m pip install pyyaml)") from exc


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPOSE = ROOT / "deploy" / "compose" / "phase1.yml"
INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:-|:\?)([^}]*))?\}")
SECRET_ENV_NAMES = {
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "RUSTFS_ACCESS_KEY",
    "RUSTFS_SECRET_KEY",
    "RUSTFS_SSE_S3_MASTER_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID",
    # These are consumed by pydantic Settings and must come from the external
    # CRASHCAP runtime env file, not from the committed Compose mapping.
    "CRASHCAP_DATABASE_URL",
    "CRASHCAP_REDIS_URL",
    "CRASHCAP_S3_ACCESS_KEY",
    "CRASHCAP_S3_SECRET_KEY",
}
LEGACY_APPLICATION_ENV_PREFIXES = (
    "APP_",
    "API_",
    "DATABASE_",
    "REDIS_",
    "S3_",
    "PRESIGN_",
    "RAW_",
    "MICROSOFT_",
    "SYMBOL_",
    "CORE_",
)
CRASHCAP_REQUIRED_EXPLICIT = {
    "CRASHCAP_ENVIRONMENT",
    "CRASHCAP_QUEUE_MODE",
    "CRASHCAP_TASK_HANDOFF_MODE",
    "CRASHCAP_TASK_RECEIPT_MODE",
    "CRASHCAP_TASK_LEASE_SECONDS",
    "CRASHCAP_CANONICAL_ASSEMBLY_MODE",
    "CRASHCAP_SYMBOL_PROJECTION_MODE",
    "CRASHCAP_ARTIFACT_BLOB_DEDUP_MODE",
    "CRASHCAP_ARTIFACT_BLOB_CLAIM_LEASE_SECONDS",
    "CRASHCAP_OBJECT_STORE_BACKEND",
    "CRASHCAP_S3_ENDPOINT_URL",
    "CRASHCAP_S3_PUBLIC_ENDPOINT_URL",
    "CRASHCAP_S3_REGION",
    "CRASHCAP_S3_BUCKET",
    "CRASHCAP_S3_SSE",
    "CRASHCAP_PRESIGN_PUT_TTL_SECONDS",
    "CRASHCAP_PRESIGN_GET_TTL_SECONDS",
    "CRASHCAP_RAW_DOWNLOAD_ENABLED",
    "CRASHCAP_EXTERNAL_BIND_HOST",
    "CRASHCAP_TRUSTED_INTRANET_ACKNOWLEDGED",
    "CRASHCAP_CORE_EXECUTOR",
    "CRASHCAP_CORE_IMAGE",
    "CRASHCAP_CORE_IMAGE_DIGEST",
    "CRASHCAP_CORE_NETWORK",
    "CRASHCAP_SYMBOLICATOR_URL",
    "CRASHCAP_SYMBOLICATOR_VERSION",
    "CRASHCAP_SYMBOLICATOR_TIMEOUT_SECONDS",
    "CRASHCAP_UNIFIED_SYMBOL_ROOT",
    "CRASHCAP_TASK_TMP_ROOT",
}
CRASHCAP_RETENTION_EXPLICIT = {
    "CRASHCAP_ENVIRONMENT",
    "CRASHCAP_QUEUE_MODE",
    "CRASHCAP_OBJECT_STORE_BACKEND",
    "CRASHCAP_S3_ENDPOINT_URL",
    "CRASHCAP_S3_PUBLIC_ENDPOINT_URL",
    "CRASHCAP_S3_REGION",
    "CRASHCAP_S3_BUCKET",
    "CRASHCAP_S3_SSE",
    "CRASHCAP_EXTERNAL_BIND_HOST",
    "CRASHCAP_SCHEMA_ROOT",
    "CRASHCAP_RETENTION_INTERVAL_SECONDS",
    "CRASHCAP_RETENTION_BATCH_SIZE",
}
CRASHCAP_RELAY_EXPLICIT = {
    "CRASHCAP_ENVIRONMENT",
    "CRASHCAP_QUEUE_MODE",
    "CRASHCAP_TASK_HANDOFF_MODE",
    "CRASHCAP_TASK_RECEIPT_MODE",
    "CRASHCAP_TASK_LEASE_SECONDS",
    "CRASHCAP_RELAY_LEASE_SECONDS",
    "CRASHCAP_RELAY_POLL_SECONDS",
    "CRASHCAP_RELAY_BACKOFF_BASE_SECONDS",
    "CRASHCAP_RELAY_BACKOFF_MAX_SECONDS",
    "CRASHCAP_OBJECT_STORE_BACKEND",
    "CRASHCAP_SCHEMA_ROOT",
    "CRASHCAP_EXTERNAL_BIND_HOST",
}
RUNTIME_REQUIRED = {
    "CRASHCAP_DATABASE_URL",
    "CRASHCAP_REDIS_URL",
    "CRASHCAP_S3_ACCESS_KEY",
    "CRASHCAP_S3_SECRET_KEY",
}
SERVICES = {
    "postgres",
    "redis",
    "rustfs",
    "storage-init",
    "s3-gateway",
    "symbols-init",
    "symbolicator",
    "symbolicator-gateway",
    "migrate",
    "api",
    "relay",
    "worker",
    "worker-verify",
    "worker-ingest",
    "worker-dump-large",
    "otel-collector",
    "ops-docker-proxy",
    "ops-exporter",
    "retention",
    "frontend",
}
EXPECTED_NETWORKS = {
    "postgres": {"data"},
    "redis": {"data"},
    "rustfs": {"data", "observability"},
    "storage-init": {"data"},
    "s3-gateway": {"edge", "data"},
    "symbolicator": {"analysis", "symbolicator-egress", "observability"},
    "otel-collector": {"observability"},
    "symbolicator-gateway": {"core", "analysis"},
    "migrate": {"data"},
    "api": {"edge", "app", "data"},
    "relay": {"data"},
    "worker": {"app", "data", "analysis"},
    "worker-verify": {"app", "data", "analysis"},
    "worker-ingest": {"app", "data", "analysis"},
    "worker-dump-large": {"app", "data", "analysis"},
    "ops-docker-proxy": {"app"},
    "ops-exporter": {"edge", "app", "observability"},
    "retention": {"data"},
    "frontend": {"edge"},
}


class Gate:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def ok(self, check: str) -> None:
        self.passed.append(check)

    def fail(self, check: str) -> None:
        self.errors.append(check)

    def warn(self, check: str) -> None:
        self.warnings.append(check)


def load_env_file(path: Path | None) -> dict[str, str]:
    values: dict[str, str] = {}
    if path is None:
        return values
    source = (
        sys.stdin.read().splitlines()
        if str(path) == "-"
        else path.read_text(encoding="utf-8").splitlines()
    )
    for number, line in enumerate(source, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise SystemExit(f"invalid env-file line {path}:{number}")
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def resolve(value: Any, env: dict[str, str]) -> Any:
    if not isinstance(value, str):
        return value

    def replacement(match: re.Match[str]) -> str:
        name, operator, argument = match.groups()
        present = env.get(name)
        if present is not None and present != "":
            return present
        if operator == ":-":
            return argument or ""
        # Do not fail on :? in the static checker.  The value is deliberately
        # represented as an empty marker, while the real Compose invocation
        # remains responsible for requiring the external file.
        return "<required-external-value>"

    return INTERPOLATION.sub(replacement, value)


def is_plain_http_endpoint(value: Any) -> bool:
    parsed = urlsplit(str(value).strip())
    return (
        parsed.scheme == "http"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def exact_http_origins(value: Any) -> list[str]:
    origins: list[str] = []
    for item in str(value).split(","):
        origin = item.strip()
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "*" in origin
        ):
            return []
        normalized = f"http://{parsed.netloc}"
        if normalized not in origins:
            origins.append(normalized)
    return origins


def parse_published_port(ports: Any, env: dict[str, str]) -> tuple[str, int, int] | None:
    if not isinstance(ports, list) or len(ports) != 1:
        return None
    expanded = str(resolve(ports[0], env))
    pieces = expanded.rsplit(":", 2)
    if len(pieces) != 3:
        return None
    host = pieces[0].strip().strip("[]")
    try:
        published = int(pieces[1])
        target = int(pieces[2].split("/", 1)[0])
    except ValueError:
        return None
    return host, published, target


def gateway_config_violations(text: str) -> list[str]:
    required = (
        "listen 9000;",
        "client_max_body_size 256m;",
        "proxy_pass http://rustfs:9000;",
        "proxy_set_header Host $http_host;",
        "proxy_request_buffering off;",
        "proxy_buffering off;",
        "log_format s3_gateway",
        "$uri",
    )
    violations = [f"missing {token}" for token in required if token not in text]
    log_format = re.search(r"log_format\s+s3_gateway\s+(.+?);", text, flags=re.DOTALL)
    log_variables = re.findall(r"\$[A-Za-z0-9_]+", log_format.group(1)) if log_format else []
    if log_variables != [
        "$request_method",
        "$uri",
        "$http_host",
        "$status",
        "$body_bytes_sent",
    ]:
        violations.append("access log must contain only method, URI, Host, status and bytes")
    if "proxy_pass http://rustfs:9000/" in text:
        violations.append("proxy_pass must not append or replace the original URI")
    if re.search(r"\$(?:request|request_uri|args|query_string)\b", text):
        violations.append("access log may expose the presigned query string")
    if "https://" in text or "ssl_certificate" in text or re.search(r"listen\s+9000\s+ssl", text):
        violations.append("gateway must remain HTTP-only")
    return violations


def network_names(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item) for item in value}
    if isinstance(value, dict):
        return {str(item) for item in value}
    return set()


def service_env(service: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    raw = service.get("environment", {})
    if isinstance(raw, list):
        result: dict[str, Any] = {}
        for item in raw:
            if isinstance(item, str) and "=" in item:
                key, value = item.split("=", 1)
                result[key] = resolve(value, env)
        return result
    if not isinstance(raw, dict):
        return {}
    return {str(key): resolve(value, env) for key, value in raw.items()}


def service_env_files(service: dict[str, Any]) -> list[str]:
    raw = service.get("env_file", [])
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict) and isinstance(item.get("path"), str):
            result.append(item["path"])
    return result


def resolve_local_extends(services: dict[str, Any]) -> dict[str, Any]:
    """Resolve the narrow same-file Compose `extends` form used by workers."""

    resolved: dict[str, Any] = {}

    def one(name: str, stack: set[str]) -> dict[str, Any]:
        if name in resolved:
            return resolved[name]
        if name in stack:
            raise ValueError(f"cyclic Compose extends at {name}")
        raw = services.get(name)
        if not isinstance(raw, dict):
            return {}
        result: dict[str, Any] = {}
        extends = raw.get("extends")
        if isinstance(extends, dict) and isinstance(extends.get("service"), str):
            base_name = str(extends["service"])
            result = copy.deepcopy(one(base_name, stack | {name}))
        for key, value in raw.items():
            if key == "extends":
                continue
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = {**result[key], **copy.deepcopy(value)}
            else:
                result[key] = copy.deepcopy(value)
        resolved[name] = result
        return result

    for service_name in services:
        one(str(service_name), set())
    return resolved


def check_bind(gate: Gate, service_name: str, ports: Any, env: dict[str, str]) -> None:
    if not isinstance(ports, list) or not ports:
        gate.fail(f"{service_name} must publish an explicit trusted-intranet port")
        return
    for port in ports:
        expanded = str(resolve(port, env))
        # Compose short syntax is host_ip:published:target.  The Phase 1 file
        # uses IPv4 defaults; retain a conservative check for IPv6 forms too.
        pieces = expanded.rsplit(":", 2)
        if len(pieces) != 3:
            gate.fail(f"{service_name} port is not host_ip:published:target")
            continue
        host = pieces[0].strip().strip("[]")
        if host in {
            "",
            "0.0.0.0",  # noqa: S104 - deliberate rejection target
            "::",
            "*",
            "<required-external-value>",
        }:
            gate.fail(f"{service_name} has wildcard/public bind {host or '<empty>'}")
            continue
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            gate.fail(f"{service_name} bind is not an IP literal: {host}")
            continue
        if not (address.is_private or address.is_loopback or address.is_link_local):
            gate.fail(f"{service_name} bind is publicly routable: {host}")
            continue
        gate.ok(f"{service_name} bind is limited to {host}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument(
        "--env-file",
        type=Path,
        help="optional external env file; values are never printed",
    )
    parser.add_argument(
        "--runtime-env-file",
        type=Path,
        help="optional external CRASHCAP_* runtime env file to validate; values are never printed",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    compose_path = args.compose.resolve()
    if not compose_path.is_file():
        print(f"ERROR: Compose file not found: {compose_path}", file=sys.stderr)
        return 2
    try:
        document = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR: cannot parse Compose YAML: {exc}", file=sys.stderr)
        return 2
    if not isinstance(document, dict):
        print("ERROR: Compose document must be a mapping", file=sys.stderr)
        return 2

    env = dict(os.environ)
    env.update(load_env_file(args.env_file))
    runtime_env: dict[str, str] = {}
    if args.runtime_env_file is not None:
        try:
            runtime_env = load_env_file(args.runtime_env_file)
        except OSError as exc:
            print(f"ERROR: cannot read runtime env file: {exc}", file=sys.stderr)
            return 2
    gate = Gate()
    services = document.get("services")
    if not isinstance(services, dict):
        gate.fail("services mapping is present")
        services = {}
    else:
        try:
            services = resolve_local_extends(services)
        except ValueError as exc:
            gate.fail(str(exc))
        actual = set(services)
        missing = SERVICES - actual
        extra = actual - SERVICES
        if missing:
            gate.fail(f"required services missing: {', '.join(sorted(missing))}")
        else:
            gate.ok(
                "PostgreSQL, Redis, private RustFS, S3 Gateway/bootstrap, "
                "Symbolicator/Gateway, one-shot migration, API, outbox relay, isolated Workers, "
                "retention and Frontend are declared"
            )
        if extra:
            gate.warn(f"additional services declared: {', '.join(sorted(extra))}")

    networks = document.get("networks")
    if not isinstance(networks, dict):
        gate.fail("networks mapping is present")
        networks = {}
    for network_name in ("app", "data", "analysis", "core"):
        network = networks.get(network_name)
        if not isinstance(network, dict) or network.get("internal") is not True:
            gate.fail(f"{network_name} network is not internal")
        else:
            gate.ok(f"{network_name} network is internal")
    egress = networks.get("symbolicator-egress")
    if not isinstance(egress, dict) or egress.get("internal") is True:
        gate.fail("symbolicator-egress must allow only the host firewall-controlled egress")
    else:
        gate.ok("Symbolicator egress is a separate non-internal network")

    for service_name, expected in EXPECTED_NETWORKS.items():
        service = services.get(service_name)
        if not isinstance(service, dict):
            continue
        actual = network_names(service.get("networks"))
        if actual != expected:
            gate.fail(f"{service_name} networks must be {sorted(expected)}, found {sorted(actual)}")
        else:
            gate.ok(f"{service_name} network membership is isolated")

    symbolicator = services.get("symbolicator", {})
    gateway = services.get("symbolicator-gateway", {})
    declared_volumes = document.get("volumes", {})
    company_sdk_mount = "phase1-company-sdk:/symbols/company-sdk:ro"
    if (
        isinstance(symbolicator, dict)
        and company_sdk_mount in symbolicator.get("volumes", [])
        and isinstance(declared_volumes, dict)
        and "phase1-company-sdk" in declared_volumes
    ):
        gate.ok("Symbolicator has a deployment-managed read-only company SDK source volume")
    else:
        gate.fail("Symbolicator company SDK source volume is missing or writable")
    gateway_env = service_env(gateway, env) if isinstance(gateway, dict) else {}
    if "COMPANY_SDK_SYMBOL_PATH" in gateway_env:
        gate.ok("Gateway exposes the optional deployment-owned company SDK source path")
    else:
        gate.fail("Gateway must expose an optional company SDK source path")

    images = {
        name: str(services.get(name, {}).get("image", ""))
        for name in ("postgres", "redis", "rustfs", "symbolicator", "otel-collector")
        if isinstance(services.get(name), dict)
    }
    expected_rustfs = (
        "ghcr.io/rustfs/rustfs@sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332"
        "965ae0c55fe8b3afed89c831"
    )
    expected_symbolicator = (
        "ghcr.io/getsentry/symbolicator@sha256:9709445e143059f35812a3999370e235"
        "4e3a99ef194068ffa4f87bbd491cb959"
    )
    expected_otel_collector = (
        "otel/opentelemetry-collector-contrib@sha256:f2f01157055a9b2aab9df7118e1f1c9"
        "abf345e99b23bc7a2bc791db374a7d0f6"
    )
    if images.get("rustfs") == expected_rustfs:
        gate.ok("RustFS uses the P0-E01 qualified digest")
    else:
        gate.fail("RustFS image is not the qualified P0-E01 digest")
    if images.get("symbolicator") == expected_symbolicator:
        gate.ok("Symbolicator uses the P0-B01 pinned digest")
    else:
        gate.fail("Symbolicator image is not the pinned P0-B01 digest")
    if images.get("otel-collector") == expected_otel_collector:
        gate.ok("OTel collector uses the reviewed contrib 0.157.0 digest")
    else:
        gate.fail("OTel collector image is not the reviewed contrib digest")
    for name in ("postgres", "redis"):
        image = images.get(name, "")
        if image and ":latest" not in image and "@sha256:" not in image:
            gate.ok(f"{name} image uses an explicit release tag")
        elif not image:
            gate.fail(f"{name} image is missing")
        else:
            gate.fail(f"{name} image must not use latest")

    for name in (
        "postgres",
        "redis",
        "rustfs",
        "storage-init",
        "symbolicator",
        "symbolicator-gateway",
        "migrate",
        "relay",
        "otel-collector",
    ):
        service = services.get(name, {})
        if isinstance(service, dict) and service.get("ports"):
            gate.fail(f"{name} must not publish a host port")
        else:
            gate.ok(f"{name} has no published host port")
    rustfs = services.get("rustfs", {})
    rustfs_secrets = rustfs.get("secrets", []) if isinstance(rustfs, dict) else []
    rustfs_command = str(rustfs.get("command", "")) if isinstance(rustfs, dict) else ""
    if (
        "rustfs_sse_s3_master_key" in str(rustfs_secrets)
        and "/run/secrets/rustfs_sse_s3_master_key" in rustfs_command
        and "RUSTFS_SSE_S3_MASTER_KEY" in rustfs_command
    ):
        gate.ok("RustFS injects the SSE-S3 master key from an external secret")
    else:
        gate.fail("RustFS must inject its SSE-S3 master key from an external secret")
    check_bind(gate, "api", services.get("api", {}).get("ports"), env)
    check_bind(gate, "frontend", services.get("frontend", {}).get("ports"), env)
    check_bind(gate, "s3-gateway", services.get("s3-gateway", {}).get("ports"), env)
    check_bind(gate, "ops-exporter", services.get("ops-exporter", {}).get("ports"), env)

    s3_gateway = services.get("s3-gateway", {})
    s3_gateway_config = ROOT / "deploy" / "s3-gateway" / "nginx.conf"
    s3_gateway_dockerfile = ROOT / "deploy" / "s3-gateway" / "Dockerfile"
    try:
        s3_gateway_config_text = s3_gateway_config.read_text(encoding="utf-8")
        s3_gateway_dockerfile_text = s3_gateway_dockerfile.read_text(encoding="utf-8")
    except OSError:
        s3_gateway_config_text = ""
        s3_gateway_dockerfile_text = ""
    gateway_violations = gateway_config_violations(s3_gateway_config_text)
    if gateway_violations:
        for violation in gateway_violations:
            gate.fail(f"S3 Gateway config: {violation}")
    else:
        gate.ok("S3 Gateway preserves signed Host/URI, streams requests and enforces 256 MiB")
        gate.ok("S3 Gateway logs omit presigned query strings and remains HTTP-only")
    if (
        "NGINX_IMAGE=nginx:" in s3_gateway_dockerfile_text
        and "@sha256:" in s3_gateway_dockerfile_text
        and "USER 10001:10001" in s3_gateway_dockerfile_text
        and isinstance(s3_gateway, dict)
        and s3_gateway.get("read_only") is True
        and not s3_gateway.get("secrets")
    ):
        gate.ok("S3 Gateway is digest-pinned, non-root, read-only and receives no secrets")
    else:
        gate.fail(
            "S3 Gateway image/runtime must be digest-pinned, non-root, read-only and secret-free"
        )

    storage_init = services.get("storage-init", {})
    storage_init_env = service_env(storage_init, env) if isinstance(storage_init, dict) else {}
    storage_init_secrets = storage_init.get("secrets", []) if isinstance(storage_init, dict) else []
    cors_origins = exact_http_origins(storage_init_env.get("S3_CORS_ALLOWED_ORIGINS", ""))
    if (
        storage_init_env.get("S3_ENDPOINT") == "http://rustfs:9000"
        and storage_init_env.get("S3_ACCESS_KEY_FILE") == "/run/secrets/rustfs_access_key"
        and storage_init_env.get("S3_SECRET_KEY_FILE") == "/run/secrets/rustfs_secret_key"
        and {str(item) for item in storage_init_secrets}
        == {"rustfs_access_key", "rustfs_secret_key"}
        and isinstance(storage_init, dict)
        and storage_init.get("read_only") is True
        and cors_origins
    ):
        gate.ok("Storage bootstrap uses private RustFS, secret files and exact HTTP CORS origins")
    else:
        gate.fail(
            "Storage bootstrap must use private RustFS, secret files and exact HTTP CORS origins"
        )

    for name in SERVICES:
        service = services.get(name)
        if not isinstance(service, dict):
            continue
        values = service_env(service, env)
        for key in SECRET_ENV_NAMES:
            if key in values:
                gate.fail(
                    f"{name} injects {key} directly; use the external CRASHCAP_* runtime env file"
                )
        if service.get("cap_drop") != ["ALL"]:
            gate.fail(f"{name} does not drop all Linux capabilities")

    ops_exporter = services.get("ops-exporter", {})
    if isinstance(ops_exporter, dict) and ops_exporter.get("read_only") is True:
        gate.ok("ops-exporter filesystem is read-only")
    else:
        gate.fail("ops-exporter must run with a read-only root filesystem")
    ops_volumes = ops_exporter.get("volumes", []) if isinstance(ops_exporter, dict) else []
    expected_ops_targets = {"/host/rustfs", "/host/symbols", "/host/symbolicator-cache"}
    actual_ops_targets = {
        str(item.get("target"))
        for item in ops_volumes
        if isinstance(item, dict) and item.get("target") in expected_ops_targets
    }
    readonly_ops_targets = {
        str(item.get("target"))
        for item in ops_volumes
        if isinstance(item, dict)
        and item.get("target") in expected_ops_targets
        and item.get("read_only") is True
    }
    if actual_ops_targets == expected_ops_targets and readonly_ops_targets == expected_ops_targets:
        gate.ok("ops-exporter mounts only the reviewed data volumes read-only")
    else:
        gate.fail("ops-exporter data-volume mounts are missing or writable")
    if isinstance(ops_exporter, dict) and not ops_exporter.get("secrets"):
        gate.ok("ops-exporter has no secret mounts")
    else:
        gate.fail("ops-exporter must not receive application secrets")
    exporter_dockerfile = ROOT / "deploy" / "ops-exporter" / "Dockerfile"
    try:
        exporter_dockerfile_text = exporter_dockerfile.read_text(encoding="utf-8")
    except OSError:
        exporter_dockerfile_text = ""
    if (
        "PYTHON_IMAGE=python:" in exporter_dockerfile_text
        and "@sha256:" in exporter_dockerfile_text
    ):
        gate.ok("ops-exporter base image is digest-pinned")
    else:
        gate.fail("ops-exporter Dockerfile must use a digest-pinned base image")
    docker_proxy = services.get("ops-docker-proxy", {})
    docker_proxy_volumes = docker_proxy.get("volumes", []) if isinstance(docker_proxy, dict) else []
    docker_socket_mounts = [
        item
        for item in docker_proxy_volumes
        if isinstance(item, dict) and "docker.sock" in str(item.get("target"))
    ]
    if (
        len(docker_socket_mounts) == 1
        and docker_socket_mounts[0].get("read_only") is True
        and isinstance(docker_proxy, dict)
        and not docker_proxy.get("ports")
    ):
        gate.ok("ops-docker-proxy exposes only a read-only internal Docker socket")
    else:
        gate.fail("ops-docker-proxy Docker socket must be read-only and un published")
    if not any(
        isinstance(item, str) and "ops_docker_proxy.py" in item
        for item in (docker_proxy.get("entrypoint", []) if isinstance(docker_proxy, dict) else [])
    ):
        gate.fail("ops-docker-proxy must run the allowlisted read-only proxy")
    else:
        gate.ok("ops-docker-proxy runs the allowlisted read-only proxy")
    exporter_has_socket = any(
        isinstance(item, dict) and "docker.sock" in str(item.get("target"))
        for item in (ops_exporter.get("volumes", []) if isinstance(ops_exporter, dict) else [])
    )
    if exporter_has_socket:
        gate.fail("ops-exporter must not mount the Docker socket directly")
    else:
        gate.ok("ops-exporter reaches Docker only through the allowlisted proxy")
    proxy_env = service_env(docker_proxy, env)
    if proxy_env.get("OPS_DOCKER_PROXY_PROJECT") not in {
        None,
        "",
        "<required-external-value>",
    }:
        gate.ok("ops-docker-proxy pins the Compose project filter")
    else:
        gate.fail("ops-docker-proxy must pin a Compose project filter")
    proxy_source = ROOT / "scripts" / "phase1" / "ops_docker_proxy.py"
    try:
        proxy_source_text = proxy_source.read_text(encoding="utf-8")
    except OSError:
        proxy_source_text = ""
    if (
        "filter_containers" in proxy_source_text
        and "com.docker.compose.project" in proxy_source_text
        and "METHOD_NOT_ALLOWED" in proxy_source_text
    ):
        gate.ok("ops-docker-proxy source enforces project/service filtering and rejects writes")
    else:
        gate.fail("ops-docker-proxy source is missing its read-only allowlist enforcement")

    otel_collector = services.get("otel-collector", {})
    otel_config = ROOT / "deploy" / "ops-exporter" / "otel-collector.yml"
    try:
        otel_config_text = otel_config.read_text(encoding="utf-8")
    except OSError:
        otel_config_text = ""
    if (
        isinstance(otel_collector, dict)
        and otel_collector.get("read_only") is True
        and not otel_collector.get("ports")
        and "otel-collector.yml:/etc/otelcol/config.yml:ro" in str(otel_collector.get("volumes"))
        and all(
            token in otel_config_text
            for token in (
                "statsd:",
                "count/rustfs:",
                "spanmetrics/rustfs:",
                "prometheus:",
            )
        )
        and "logging:" not in otel_config_text
    ):
        gate.ok("OTel collector is internal, read-only and exports RustFS/StatsD metrics only")
    else:
        gate.fail("OTel collector must be internal/read-only with the reviewed metrics-only config")

    symbolicator_config = ROOT / "deploy" / "symbolicator" / "config.yml"
    try:
        symbolicator_config_text = symbolicator_config.read_text(encoding="utf-8")
    except OSError:
        symbolicator_config_text = ""
    symbolicator_env = service_env(services.get("symbolicator", {}), env)
    if (
        symbolicator_env.get("SYMBOLICATOR_STATSD_ADDR") == "otel-collector:8125"
        and 'statsd: "${SYMBOLICATOR_STATSD_ADDR}"' in symbolicator_config_text
        and "prefix: symbolicator" in symbolicator_config_text
    ):
        gate.ok("Symbolicator config exports StatsD metrics to the internal collector")
    else:
        gate.fail(
            "Symbolicator config must reference SYMBOLICATOR_STATSD_ADDR and "
            "use the reviewed prefix"
        )

    api_env = service_env(services.get("api", {}), env)
    worker_env = service_env(services.get("worker", {}), env)
    relay_env = service_env(services.get("relay", {}), env)
    retention_env = service_env(services.get("retention", {}), env)
    for name, values in (("api", api_env), ("worker", worker_env)):
        mode = str(values.get("CRASHCAP_ARTIFACT_BLOB_DEDUP_MODE", ""))
        lease = str(values.get("CRASHCAP_ARTIFACT_BLOB_CLAIM_LEASE_SECONDS", ""))
        if mode == "off":
            gate.ok(f"{name} defaults Artifact Blob dedup rollout to off")
        elif mode in {"shadow", "active"}:
            gate.warn(f"{name} enables Artifact Blob dedup rollout mode {mode}")
        else:
            gate.fail(f"{name} Artifact Blob dedup mode is invalid")
        try:
            if 30 <= int(lease) <= 7200:
                gate.ok(f"{name} declares a bounded Artifact Blob claim lease")
            else:
                gate.fail(f"{name} Artifact Blob claim lease is outside 30..7200 seconds")
        except ValueError:
            gate.fail(f"{name} Artifact Blob claim lease is not an integer")
    migrate = services.get("migrate", {})
    if isinstance(migrate, dict):
        migrate_files = service_env_files(migrate)
        migrate_entrypoint = migrate.get("entrypoint", [])
        if not any("PHASE1_RUNTIME_ENV_FILE" in item for item in migrate_files):
            gate.fail("migrate must load the external PHASE1_RUNTIME_ENV_FILE")
        else:
            gate.ok("migrate loads the external database URL")
        if migrate.get("restart") != "no":
            gate.fail('migrate must use restart: "no"')
        else:
            gate.ok("migrate is a one-shot service")
        if migrate.get("read_only") is not True:
            gate.fail("migrate must use a read-only root filesystem")
        else:
            gate.ok("migrate filesystem is read-only")
        if "crashcap-migrate" not in str(migrate_entrypoint):
            gate.fail("migrate must use the crashcap-migrate entrypoint")
        else:
            gate.ok("migrate uses the dedicated Alembic entrypoint")
        migrate_dependencies = migrate.get("depends_on", {})
        postgres_dependency = (
            migrate_dependencies.get("postgres", {})
            if isinstance(migrate_dependencies, dict)
            else {}
        )
        if (
            isinstance(postgres_dependency, dict)
            and postgres_dependency.get("condition") == "service_healthy"
        ):
            gate.ok("migrate waits for healthy PostgreSQL")
        else:
            gate.fail("migrate must wait for healthy PostgreSQL")
    worker_names = ("worker", "worker-verify", "worker-ingest", "worker-dump-large")
    for name in ("api", *worker_names):
        service = services.get(name, {})
        values = service_env(service, env)
        env_files = service_env_files(service)
        if not any("PHASE1_RUNTIME_ENV_FILE" in item for item in env_files):
            gate.fail(f"{name} must load the external PHASE1_RUNTIME_ENV_FILE")
        else:
            gate.ok(f"{name} loads external CRASHCAP_* runtime settings")
        unexpected = sorted(
            key for key in values if not key.startswith("CRASHCAP_") and key not in {"PORT"}
        )
        if unexpected:
            gate.fail(f"{name} contains non-CRASHCAP application env: {', '.join(unexpected)}")
        missing = sorted(CRASHCAP_REQUIRED_EXPLICIT - set(values))
        if missing:
            gate.fail(f"{name} is missing explicit CRASHCAP_* settings: {', '.join(missing)}")
        else:
            gate.ok(f"{name} declares the required CRASHCAP_* settings")
        legacy = sorted(key for key in values if key.startswith(LEGACY_APPLICATION_ENV_PREFIXES))
        if legacy:
            gate.fail(f"{name} still uses legacy application env names: {', '.join(legacy)}")
        if args.runtime_env_file is None:
            gate.warn(f"{name} runtime CRASHCAP_* env file was not inspected")
        else:
            missing_runtime = sorted(RUNTIME_REQUIRED - set(runtime_env))
            invalid_runtime = sorted(key for key in runtime_env if not key.startswith("CRASHCAP_"))
            if missing_runtime:
                gate.fail(
                    f"runtime env file is missing Settings values for {name}: "
                    f"{', '.join(missing_runtime)}"
                )
            if invalid_runtime:
                gate.fail(
                    "runtime env file contains non-CRASHCAP names: " + ", ".join(invalid_runtime)
                )
            if not missing_runtime and not invalid_runtime:
                gate.ok(
                    "external runtime env file contains the required CRASHCAP_* secret settings"
                )
    relay = services.get("relay", {})
    if isinstance(relay, dict):
        relay_files = service_env_files(relay)
        if not any("PHASE1_RUNTIME_ENV_FILE" in item for item in relay_files):
            gate.fail("relay must load the external PHASE1_RUNTIME_ENV_FILE")
        else:
            gate.ok("relay loads external database and Redis settings")
        missing_relay = sorted(CRASHCAP_RELAY_EXPLICIT - set(relay_env))
        if missing_relay:
            gate.fail("relay is missing explicit CRASHCAP_* settings: " + ", ".join(missing_relay))
        else:
            gate.ok("relay declares its handoff, lease and backoff settings")
        if relay.get("read_only") is not True:
            gate.fail("relay must use a read-only root filesystem")
        else:
            gate.ok("relay filesystem is read-only")
        if "crashcap-relay" not in str(relay.get("entrypoint", [])):
            gate.fail("relay must use the crashcap-relay entrypoint")
        else:
            gate.ok("relay uses the dedicated outbox entrypoint")
        relay_dependencies = relay.get("depends_on", {})
        if not (
            isinstance(relay_dependencies, dict)
            and relay_dependencies.get("postgres", {}).get("condition") == "service_healthy"
            and relay_dependencies.get("redis", {}).get("condition") == "service_healthy"
        ):
            gate.fail("relay must wait for healthy PostgreSQL and Redis")
        else:
            gate.ok("relay waits for healthy PostgreSQL and Redis")
    retention = services.get("retention", {})
    if isinstance(retention, dict):
        retention_files = service_env_files(retention)
        if not any("PHASE1_RUNTIME_ENV_FILE" in item for item in retention_files):
            gate.fail("retention must load the external PHASE1_RUNTIME_ENV_FILE")
        else:
            gate.ok("retention loads external CRASHCAP_* runtime settings")
        unexpected_retention = sorted(
            key for key in retention_env if not key.startswith("CRASHCAP_") and key not in {"PORT"}
        )
        if unexpected_retention:
            gate.fail(
                "retention contains non-CRASHCAP application env: "
                + ", ".join(unexpected_retention)
            )
        missing_retention = sorted(CRASHCAP_RETENTION_EXPLICIT - set(retention_env))
        if missing_retention:
            gate.fail(
                "retention is missing explicit CRASHCAP_* settings: " + ", ".join(missing_retention)
            )
        else:
            gate.ok("retention declares the required CRASHCAP_* settings")
        if args.runtime_env_file is None:
            gate.warn("retention runtime CRASHCAP_* env file was not inspected")
        else:
            missing_runtime = sorted(RUNTIME_REQUIRED - set(runtime_env))
            invalid_runtime = sorted(key for key in runtime_env if not key.startswith("CRASHCAP_"))
            if missing_runtime:
                gate.fail(
                    "runtime env file is missing Settings values for retention: "
                    + ", ".join(missing_runtime)
                )
            if invalid_runtime:
                gate.fail(
                    "runtime env file contains non-CRASHCAP names: " + ", ".join(invalid_runtime)
                )
            if not missing_runtime and not invalid_runtime:
                gate.ok(
                    "external runtime env file contains the required CRASHCAP_* secret settings"
                )

    for name, values in (
        ("api", api_env),
        ("worker", worker_env),
        ("retention", retention_env),
    ):
        if is_plain_http_endpoint(values.get("CRASHCAP_S3_ENDPOINT_URL", "")):
            gate.ok(f"{name} uses an HTTP-only internal S3 endpoint")
        else:
            gate.fail(f"{name} must use http:// for the internal RustFS endpoint")
        if name == "retention":
            continue
        raw_download = str(values.get("CRASHCAP_RAW_DOWNLOAD_ENABLED", "")).lower()
        if raw_download == "false":
            gate.ok(f"{name} defaults CRASHCAP_RAW_DOWNLOAD_ENABLED=false")
        else:
            gate.warn(f"{name} raw download is enabled; trusted-intranet warning is mandatory")
        put_ttl = str(values.get("CRASHCAP_PRESIGN_PUT_TTL_SECONDS", "900"))
        get_ttl = str(values.get("CRASHCAP_PRESIGN_GET_TTL_SECONDS", "900"))
        try:
            if int(put_ttl) > 900 or int(get_ttl) > 900:
                gate.fail(f"{name} presign TTL exceeds 900 seconds")
            else:
                gate.ok(f"{name} presign TTL is short")
        except ValueError:
            gate.fail(f"{name} presign TTL is not an integer")

    queue_limits = {
        "worker": ("dump-small", "4g", 2.0, "600"),
        "worker-verify": ("verify", "2g", 1.0, "900"),
        "worker-ingest": ("ingest", "4g", 1.0, "900"),
        "worker-dump-large": ("dump-large", "8g", 2.0, "1200"),
    }
    for name, (queue, memory, cpus, timeout) in queue_limits.items():
        service = services.get(name, {})
        values = service_env(service, env)
        if (
            values.get("CRASHCAP_WORKER_QUEUES") == queue
            and str(service.get("mem_limit")) == memory
            and float(service.get("cpus", 0)) == cpus
            and str(values.get("CRASHCAP_CORE_TIMEOUT_SECONDS")) == timeout
            and str(values.get("CRASHCAP_WORKER_PROCESSES")) == "1"
        ):
            gate.ok(f"{name} has isolated {queue} routing and resource limits")
        else:
            gate.fail(f"{name} does not match the Phase 1 {queue} resource contract")
    public_s3 = str(api_env.get("CRASHCAP_S3_PUBLIC_ENDPOINT_URL", ""))
    if is_plain_http_endpoint(public_s3):
        gate.ok("API presigned URLs use an HTTP-only trusted-intranet S3 endpoint")
    else:
        gate.fail("CRASHCAP_S3_PUBLIC_ENDPOINT_URL must use http://")
    public_parsed = urlsplit(public_s3)
    gateway_port = parse_published_port(
        services.get("s3-gateway", {}).get("ports")
        if isinstance(services.get("s3-gateway"), dict)
        else None,
        env,
    )
    try:
        public_port = public_parsed.port or (80 if public_parsed.scheme == "http" else None)
    except ValueError:
        public_port = None
    public_host = public_parsed.hostname or ""
    if public_host in SERVICES:
        gate.fail("CRASHCAP_S3_PUBLIC_ENDPOINT_URL must not contain a Compose service name")
    elif (
        gateway_port is not None
        and public_host == gateway_port[0]
        and public_port == gateway_port[1]
        and gateway_port[2] == 9000
        and public_parsed.path in {"", "/"}
    ):
        gate.ok("API public S3 endpoint exactly matches the published S3 Gateway")
    else:
        gate.fail("API public S3 endpoint must match the S3 Gateway bind and published port")
    for name, values in (("worker", worker_env), ("retention", retention_env)):
        if values.get("CRASHCAP_S3_PUBLIC_ENDPOINT_URL") == public_s3:
            gate.ok(f"{name} public S3 endpoint matches API")
        else:
            gate.fail(f"{name} public S3 endpoint must match API")

    frontend_port = parse_published_port(
        services.get("frontend", {}).get("ports")
        if isinstance(services.get("frontend"), dict)
        else None,
        env,
    )
    expected_frontend_origin = (
        f"http://{frontend_port[0]}:{frontend_port[1]}" if frontend_port is not None else ""
    )
    if expected_frontend_origin and expected_frontend_origin in cors_origins:
        gate.ok("Bucket CORS includes the exact published Frontend HTTP origin")
    else:
        gate.fail("S3_CORS_ALLOWED_ORIGINS must include the published Frontend HTTP origin")

    storage_dependents = (
        "api",
        "worker",
        "worker-verify",
        "worker-ingest",
        "worker-dump-large",
        "retention",
    )
    for name in storage_dependents:
        service = services.get(name, {})
        depends_on = service.get("depends_on", {}) if isinstance(service, dict) else {}
        storage_dependency = (
            depends_on.get("storage-init", {}) if isinstance(depends_on, dict) else {}
        )
        if (
            isinstance(storage_dependency, dict)
            and storage_dependency.get("condition") == "service_completed_successfully"
        ):
            gate.ok(f"{name} waits for successful storage bootstrap")
        else:
            gate.fail(f"{name} must wait for successful storage bootstrap")
    migration_dependents = (
        "api",
        "relay",
        "worker",
        "worker-verify",
        "worker-ingest",
        "worker-dump-large",
        "retention",
    )
    for name in migration_dependents:
        service = services.get(name, {})
        depends_on = service.get("depends_on", {}) if isinstance(service, dict) else {}
        migration_dependency = depends_on.get("migrate", {}) if isinstance(depends_on, dict) else {}
        if (
            isinstance(migration_dependency, dict)
            and migration_dependency.get("condition") == "service_completed_successfully"
        ):
            gate.ok(f"{name} waits for successful schema migration")
        else:
            gate.fail(f"{name} must wait for successful schema migration")
    if api_env.get("CRASHCAP_CORE_NETWORK") == worker_env.get("CRASHCAP_CORE_NETWORK"):
        gate.ok("API and Worker use the same CRASHCAP_CORE_NETWORK")
    else:
        gate.fail("API and Worker CRASHCAP_CORE_NETWORK values differ")
    core_network = resolve(networks.get("core", {}).get("name", ""), env)
    if api_env.get("CRASHCAP_CORE_NETWORK") == core_network:
        gate.ok("CRASHCAP_CORE_NETWORK matches the Compose core network name")
    else:
        gate.fail("CRASHCAP_CORE_NETWORK does not match the Compose core network name")
    if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(api_env.get("CRASHCAP_CORE_IMAGE_DIGEST", ""))):
        gate.ok("API CRASHCAP_CORE_IMAGE_DIGEST is a valid OCI digest")
    else:
        gate.fail("API CRASHCAP_CORE_IMAGE_DIGEST is not a valid OCI digest")
    if re.fullmatch(
        r"sha256:[0-9a-fA-F]{64}", str(worker_env.get("CRASHCAP_CORE_IMAGE_DIGEST", ""))
    ):
        gate.ok("Worker CRASHCAP_CORE_IMAGE_DIGEST is a valid OCI digest")
    else:
        gate.fail("Worker CRASHCAP_CORE_IMAGE_DIGEST is not a valid OCI digest")
    frontend_env = service_env(services.get("frontend", {}), env)
    if frontend_env.get("VITE_USE_MOCK") == "false":
        gate.ok("Frontend disables the mock API in Compose")
    else:
        gate.fail("Frontend must set VITE_USE_MOCK=false for Phase 1")
    if "VITE_API_BASE_URL" in frontend_env:
        gate.ok("Frontend uses the VITE_API_BASE_URL variable")
    else:
        gate.fail("Frontend is missing VITE_API_BASE_URL")

    worker_volumes = services.get("worker", {}).get("volumes", [])
    if any("docker.sock" in str(item) for item in worker_volumes):
        gate.ok("Worker has the explicit one-shot Core runner socket")
    else:
        gate.fail("Worker cannot launch the isolated one-shot Core runner")
    core_policy = document.get("x-core-runtime", {})
    if (
        isinstance(core_policy, dict)
        and core_policy.get("allowed_peer") == "symbolicator-gateway"
        and set(core_policy.get("denied_peer", [])) == {"postgres", "redis", "rustfs"}
    ):
        gate.ok("Core runtime policy denies PostgreSQL, Redis and RustFS")
    else:
        gate.fail("Core runtime policy does not declare the required denied peers")

    # This catches accidental committed default credentials without echoing the
    # matching line, which could itself become a secret leak in CI logs.
    raw_text = compose_path.read_text(encoding="utf-8")
    for forbidden in (
        "rustfsadmin",
        "RUSTFS_SECRET_KEY: ",
        "POSTGRES_PASSWORD: ",
        "REDIS_PASSWORD: ",
    ):
        if forbidden in raw_text:
            gate.fail(
                f"Compose contains a forbidden literal credential pattern: {forbidden.strip()}"
            )

    result = {
        "status": "PASS" if not gate.errors else "FAIL",
        "compose": str(compose_path),
        "passed_checks": gate.passed,
        "warnings": gate.warnings,
        "errors": gate.errors,
        "note": "Static only: no containers, backups, restores or capacity workload were executed.",
    }
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Phase 1 deployment static check: {result['status']}")
        print(f"Passed checks: {len(gate.passed)}")
        for warning in gate.warnings:
            print(f"WARNING: {warning}")
        for error in gate.errors:
            print(f"ERROR: {error}")
        print(result["note"])
    return 0 if not gate.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
