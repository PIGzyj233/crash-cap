from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from .object_keys import safe_filename


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WorkspaceCreate(StrictModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    retention_days: int = Field(default=180, ge=1, le=3650)


class MultipartPart(StrictModel):
    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=200)


class UploadComplete(StrictModel):
    etag: str | None = Field(default=None, max_length=200)
    multipart_upload_id: str | None = Field(default=None, max_length=1000)
    parts: list[MultipartPart] = Field(default_factory=list, max_length=10_000)


class UploadV3Init(StrictModel):
    workspace_id: str | None
    file_kind: Literal["pe", "pdb", "dmp"]
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    version: str | None = Field(default=None, min_length=1, max_length=200)
    source: Literal["api", "cli", "browser"] = "api"

    @field_validator("filename")
    @classmethod
    def validate_v3_filename(cls, value: str) -> str:
        return safe_filename(value)


class OccurrenceVersionPatch(StrictModel):
    version: str | None = Field(default=None, min_length=1, max_length=200)


class SymbolBatchReprocessRequest(StrictModel):
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
