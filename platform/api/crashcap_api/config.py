from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any, ClassVar, Literal
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


def _is_frozen_endpoint(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and (parsed.port is None or 1 <= parsed.port <= 65535)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and value.isascii()
            and not any(ord(c) <= 32 or ord(c) == 127 or c in '<>"{}|\\^`' for c in value)
        )
    except ValueError:
        return False


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
    task_handoff_mode: ClassVar[Literal["outbox"]] = "outbox"
    task_receipt_mode: ClassVar[Literal["strict"]] = "strict"
    task_lease_seconds: int = Field(default=1500, ge=30, le=7200)
    relay_lease_seconds: int = Field(default=30, ge=5, le=300)
    relay_poll_seconds: float = Field(default=0.5, ge=0.05, le=60)
    relay_backoff_base_seconds: int = Field(default=1, ge=1, le=300)
    relay_backoff_max_seconds: int = Field(default=300, ge=1, le=3600)
    canonical_assembly_mode: ClassVar[Literal["core-final"]] = "core-final"
    symbol_projection_mode: ClassVar[Literal["projection-read"]] = "projection-read"
    artifact_upload_gc_mode: Literal["off", "dry-run", "active"] = "off"
    artifact_upload_gc_accepted_hours: int = Field(default=24, ge=1, le=24 * 30)
    artifact_upload_gc_rejected_hours: int = Field(default=24 * 7, ge=24, le=24 * 90)
    artifact_upload_gc_claim_seconds: int = Field(default=300, ge=30, le=3600)

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
    core_image: str = "crash-cap/dmp-core:upload-v3"
    core_image_digest: str = (
        "sha256:fc6101e5acc50a92407ac056f212bc9a1649acc65bf686d67222b6d9a54bf389"
    )
    core_network: str = "crashcap_core"
    core_memory: str = "4g"
    core_cpus: float = Field(default=2.0, gt=0, le=64)
    core_pids_limit: int = Field(default=256, ge=32, le=4096)
    core_timeout_seconds: int = Field(default=600, ge=5, le=3600)
    core_stage_timeout_seconds: int = Field(default=600, ge=30, le=3600)
    core_stage_min_throughput_mib_s: float = Field(default=2.0, gt=0, le=1024)
    core_stage_max_timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    core_tmpfs_size: str = "512m"

    frozen_core_enabled: ClassVar[bool] = True
    frozen_analysis_enabled: ClassVar[bool] = True
    evidence_promotion_enabled: ClassVar[bool] = True
    catalog_reviews_enabled: ClassVar[bool] = True
    result_reviews_enabled: ClassVar[bool] = True
    workspace_module_roles_enabled: ClassVar[bool] = True
    catalog_source_enabled: ClassVar[bool] = True
    catalog_source_max_locations: int = Field(default=32, ge=1, le=200)
    catalog_source_max_concurrent: int = Field(default=2, ge=1, le=32)
    analysis_max_attempts: int = Field(default=3, ge=1, le=10)
    analysis_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    analysis_retry_max_seconds: int = Field(default=300, ge=1, le=7200)
    automatic_analysis_enabled: ClassVar[bool] = True
    automatic_analysis_paused: bool = False
    automatic_analysis_workspace_limit: int = Field(default=1, ge=1, le=16)
    automatic_analysis_global_limit: int = Field(default=2, ge=1, le=128)
    automatic_analysis_capacity: int = Field(default=2, ge=1, le=128)
    automatic_analysis_enumeration_limit: int = Field(default=200, ge=1, le=2000)
    automatic_analysis_release_limit: int = Field(default=50, ge=1, le=500)
    automatic_analysis_planning_lease_seconds: int = Field(default=1800, ge=30, le=7200)
    automatic_analysis_delivery_timeout_seconds: int = Field(default=1800, ge=30, le=86400)
    frozen_allow_local_core_sentinel: bool = False
    frozen_symbolicator_url: str = "http://symbolicator:3021"
    frozen_pair_source_root: str = "http://symbol-source:8081/v3/pairs"
    frozen_symbolicator_image_digest: str = (
        "sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959"
    )
    frozen_public_sources: list[dict[str, Any]] = Field(
        default_factory=lambda: [
            {
                "id": "crash-cap:microsoft",
                "type": "http",
                "url": "https://msdl.microsoft.com/download/symbols/",
                "layout": {"type": "symstore"},
                "filters": {"filetypes": ["pdb", "pe", "portablepdb"]},
                "is_public": True,
            }
        ],
        max_length=16,
    )

    symbolicator_url: str = "http://symbolicator-gateway:3021"
    symbolicator_version: str = "26.7.2"
    symbolicator_timeout_seconds: int = Field(default=30, ge=1, le=300)
    symbolicator_cache_root: Path = Path("/var/lib/crashcap/symbolicator-cache")
    normalization_version: str = "norm-v1.0"
    grouping_version: str = "group-v1.1"
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
        if self.environment != "test":
            if self.core_executor == "fake":
                raise ValueError("Uploads and analysis require a real Core executor")
            for endpoint in (self.frozen_symbolicator_url, self.frozen_pair_source_root):
                if endpoint is None or not _is_frozen_endpoint(endpoint):
                    raise ValueError(
                        "Frozen Core requires explicit managed HTTP(S) source/engine endpoints"
                    )
            if self.frozen_symbolicator_image_digest is None:
                raise ValueError(
                    "Frozen Core requires an independently configured Symbolicator digest"
                )
            self.validate_digest(self.frozen_symbolicator_image_digest)
            if self.frozen_allow_local_core_sentinel and (
                self.environment == "production" or self.core_executor != "local"
            ):
                raise ValueError(
                    "The Core sentinel is only allowed for local non-production qualification"
                )
        if self.analysis_retry_max_seconds < self.analysis_retry_base_seconds:
            raise ValueError("Analysis retry maximum must be at least the base delay")
        return self

    def is_trusted_bind(self) -> bool:
        host = self.external_bind_host.strip().strip("[]")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return self.trusted_intranet_acknowledged
        return address.is_private or address.is_loopback

    def core_stage_deadline(self, byte_count: int) -> int:
        throughput = self.core_stage_min_throughput_mib_s * 1024 * 1024
        byte_budget = int(byte_count / throughput) + 60
        return min(
            self.core_stage_max_timeout_seconds,
            max(self.core_stage_timeout_seconds, byte_budget),
        )

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
            external_bind_host="127.0.0.1",
        )
