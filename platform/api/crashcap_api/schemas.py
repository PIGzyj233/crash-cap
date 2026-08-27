from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from .object_keys import safe_filename


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WorkspaceCreate(StrictModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    retention_days: int = Field(default=180, ge=1, le=3650)


class BuildCreate(StrictModel):
    version: str = Field(min_length=1, max_length=200)
    build_number: str | None = Field(default=None, max_length=200)
    commit_sha: str | None = Field(default=None, max_length=200)
    channel: str | None = Field(default=None, max_length=100)
    architecture: Literal["x86_64"] = "x86_64"
    toolchain: str | None = Field(default=None, max_length=100)
    producer: Literal["msvc", "clang-cl", "crashpad"] | None = None
    producer_build_id: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def producer_identity_is_complete(self) -> BuildCreate:
        if (self.producer is None) != (self.producer_build_id is None):
            raise ValueError("producer and producer_build_id must be supplied together")
        return self


class PublicationGitState(StrictModel):
    revision: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[0-9A-Fa-f]+$"
    )
    worktree_state: Literal["clean", "dirty", "unknown"]


class ArtifactExpectationCreate(StrictModel):
    module_code_file: str = Field(min_length=1, max_length=255)
    kind: Literal["pe", "pdb"]
    logical_name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=8 * 1024 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("module_code_file", "logical_name")
    @classmethod
    def validate_names(cls, value: str) -> str:
        return safe_filename(value)


class BuildPublicationCreate(StrictModel):
    schema_version: Literal["1.0"]
    origin: Literal["local", "ci"]
    client_publication_id: str = Field(
        min_length=1,
        max_length=300,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    client_version: str = Field(min_length=1, max_length=100)
    git: PublicationGitState
    manifest: dict[str, Any]
    artifacts: list[ArtifactExpectationCreate] = Field(min_length=2, max_length=512)


class ArtifactUploadInit(StrictModel):
    file_kind: Literal["pe", "pdb", "source_bundle"]
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return safe_filename(value)


class ArtifactDeliveryInit(StrictModel):
    file_kind: Literal["pe", "pdb"]
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return safe_filename(value)


class ArtifactDeliveryLogical(StrictModel):
    size: int = Field(gt=0, le=2 * 1024 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArtifactDeliveryWire(StrictModel):
    encoding: Literal["identity", "zstd-v1"]
    size: int = Field(gt=0, le=2 * 1024 * 1024 * 1024 + 1024 * 1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArtifactDeliveryV2Init(StrictModel):
    file_kind: Literal["pe", "pdb"]
    filename: str = Field(min_length=1, max_length=255)
    logical: ArtifactDeliveryLogical
    wire: ArtifactDeliveryWire

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return safe_filename(value)

    @model_validator(mode="after")
    def identity_wire_matches_logical(self) -> ArtifactDeliveryV2Init:
        if self.wire.encoding == "identity" and (
            self.wire.size != self.logical.size or self.wire.sha256 != self.logical.sha256
        ):
            raise ValueError("identity wire size and sha256 must equal the logical identity")
        return self


class DumpUploadInit(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    capture_profile: Literal["light-crash", "rich-crash", "hang", "full-memory"] | None = None
    reported_build_id: str | None = None
    reported_at: datetime | None = None

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return safe_filename(value)


class MultipartPart(StrictModel):
    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=200)


class UploadComplete(StrictModel):
    etag: str | None = Field(default=None, max_length=200)
    multipart_upload_id: str | None = Field(default=None, max_length=1000)
    parts: list[MultipartPart] = Field(default_factory=list, max_length=10_000)


class ReprocessRequest(StrictModel):
    force: bool = False
    reported_build_id: str | None = None


class SymbolBatchReprocessRequest(StrictModel):
    build_id: str | None = None
    module_id: str | None = None
    occurrence_ids: list[str] = Field(default_factory=list, max_length=5000)


class InAppRulesUpdate(StrictModel):
    include_modules: list[str] = Field(default_factory=list, max_length=1000)
    exclude_modules: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("include_modules", "exclude_modules")
    @classmethod
    def validate_module_names(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            name = safe_filename(value).casefold()
            if name not in normalized:
                normalized.append(name)
        return normalized


class GroupPatch(StrictModel):
    status: Literal["open", "investigating", "fixed", "ignored"] | None = None
    owner: str | None = Field(default=None, max_length=200)
    issue_url: HttpUrl | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)


class OccurrenceTimePatch(StrictModel):
    occurred_at: datetime


class ApiPage(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = None
