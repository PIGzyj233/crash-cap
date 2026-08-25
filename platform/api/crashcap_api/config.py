from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _is_plain_http_endpoint(value: str) -> bool:
    parsed = urlsplit(value.strip())
    return (
        parsed.scheme == "http"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


class Settings(BaseSettings):
    """Deployment configuration loaded exclusively from CRASHCAP_* variables."""

    model_config = SettingsConfigDict(
        env_prefix="CRASHCAP_",
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://crashcap@postgres/crashcap"
    create_schema: bool = False

    queue_mode: Literal["dramatiq", "memory"] = "dramatiq"
    redis_url: str = "redis://redis:6379/0"
    task_handoff_mode: Literal["legacy", "shadow", "outbox"] = "legacy"
    task_receipt_mode: Literal["compat", "strict"] = "compat"
    task_lease_seconds: int = Field(default=1500, ge=30, le=7200)
    relay_lease_seconds: int = Field(default=30, ge=5, le=300)
    relay_poll_seconds: float = Field(default=0.5, ge=0.05, le=60)
    relay_backoff_base_seconds: int = Field(default=1, ge=1, le=300)
    relay_backoff_max_seconds: int = Field(default=300, ge=1, le=3600)
    canonical_assembly_mode: Literal["legacy", "shadow", "core-final"] = "legacy"
    symbol_projection_mode: Literal["legacy", "shadow-soft", "strict-writer", "projection-read"] = (
        "legacy"
    )
    build_publications_enabled: bool = False
    artifact_blob_dedup_mode: Literal["off", "shadow", "active"] = "off"
    artifact_blob_claim_lease_seconds: int = Field(default=900, ge=30, le=7200)

    object_store_backend: Literal["s3", "local"] = "s3"
    object_store_local_root: Path = Path(".runtime/objects")
    s3_endpoint_url: str = "http://rustfs:9000"
    s3_public_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "crash-cap"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_sse: Literal["AES256"] = "AES256"
    presign_put_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    presign_get_ttl_seconds: int = Field(default=300, ge=30, le=3600)

    raw_download_enabled: bool = False
    external_bind_host: str = "127.0.0.1"
    trusted_intranet_acknowledged: bool = False
    cors_origins: tuple[str, ...] = ()

    core_executor: Literal["docker", "local", "fake"] = "docker"
    core_command: str = "dmp-core"
    core_image: str = "crash-cap/dmp-core:phase1"
    core_image_digest: str = (
        "sha256:e75a50bdb953a450185c8d6666d470f9ba7f6985f6dee83e33f7c27d82f7ce9a"
    )
    core_network: str = "crashcap_core"
    core_memory: str = "4g"
    core_cpus: float = Field(default=2.0, gt=0, le=64)
    core_pids_limit: int = Field(default=256, ge=32, le=4096)
    core_timeout_seconds: int = Field(default=600, ge=5, le=3600)
    core_tmpfs_size: str = "512m"

    symbolicator_url: str = "http://symbolicator-gateway:3021"
    symbolicator_version: str = "26.7.2"
    symbolicator_timeout_seconds: int = Field(default=30, ge=1, le=300)
    symsorter_command: str = "symsorter"
    unified_symbol_root: Path = Path("/var/lib/crashcap/symbols")
    symbol_ingest_mode: Literal["symsorter", "fake"] = "symsorter"
    normalization_version: str = "norm-v1.0"
    grouping_version: str = "group-v1.0"
    exact_algorithm: str = "exact-v1.0"

    schema_root: Path = REPOSITORY_ROOT / "contracts"
    task_tmp_root: Path = Path(".runtime/tasks")
    log_level: str = "INFO"

    @field_validator("core_image_digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if not value.startswith("sha256:") or len(value) != 71:
            raise ValueError("core_image_digest must be a sha256 OCI digest")
        int(value[7:], 16)
        return value.lower()

    @field_validator("database_url")
    @classmethod
    def reject_embedded_password_in_logs(cls, value: str) -> str:
        if not value:
            raise ValueError("database_url must not be empty")
        return value

    @model_validator(mode="after")
    def validate_security_boundary(self) -> Settings:
        if not self.schema_root.is_dir():
            raise ValueError("schema_root must reference the stable contract directory")
        if self.object_store_backend == "s3" and (
            not self.s3_access_key.get_secret_value() or not self.s3_secret_key.get_secret_value()
        ):
            raise ValueError("S3 service credentials must be injected for the s3 backend")
        if self.object_store_backend == "s3":
            for field_name, endpoint in (
                ("s3_endpoint_url", self.s3_endpoint_url),
                ("s3_public_endpoint_url", self.s3_public_endpoint_url),
            ):
                if endpoint is not None and not _is_plain_http_endpoint(endpoint):
                    raise ValueError(
                        f"{field_name} must use http:// with a host and no userinfo/query/fragment"
                    )
        if self.environment == "production" and not self.is_trusted_bind():
            raise ValueError(
                "anonymous production deployment may not use a public bind; "
                "set an RFC1918/loopback host or explicitly acknowledge an internal DNS boundary"
            )
        return self

    def is_trusted_bind(self) -> bool:
        host = self.external_bind_host.strip().strip("[]")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return self.trusted_intranet_acknowledged
        return address.is_private or address.is_loopback

    @classmethod
    def for_test(cls, root: Path, database_url: str = "sqlite+pysqlite:///:memory:") -> Settings:
        return cls(
            environment="test",
            database_url=database_url,
            create_schema=True,
            queue_mode="memory",
            object_store_backend="local",
            object_store_local_root=root / "objects",
            task_tmp_root=root / "tasks",
            core_executor="fake",
            symbol_ingest_mode="fake",
            external_bind_host="127.0.0.1",
        )
