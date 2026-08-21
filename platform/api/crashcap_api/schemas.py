from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

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


class ArtifactUploadInit(StrictModel):
    file_kind: Literal["pe", "pdb", "source_bundle"]
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return safe_filename(value)


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
