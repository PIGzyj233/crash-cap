from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WireResponse(BaseModel):
    """Exact JSON representation returned by an ``/api/v3`` route."""

    model_config = ConfigDict(extra="forbid")


class ErrorDetailResponse(WireResponse):
    code: str
    message: str
    details: dict[str, Any]


class ErrorEnvelopeResponse(WireResponse):
    error: ErrorDetailResponse


class InAppRulesBodyResponse(WireResponse):
    include_modules: list[str]
    exclude_modules: list[str]


class WorkspaceResponse(WireResponse):
    id: str
    name: str
    display_name: str | None
    platform: Literal["windows"]
    default_architecture: Literal["x86_64"]
    retention_days: int
    symbol_inventory_version: int
    in_app_rule_version: int
    in_app_rules: InAppRulesBodyResponse
    created_at: str


class GroupSummaryResponse(WireResponse):
    id: str
    workspace_id: str
    group_type: Literal["exact"]
    fingerprint: str
    title: str
    status: Literal["open", "investigating", "fixed", "ignored"]
    owner: str | None
    issue_url: str | None
    occurrence_count: int
    first_seen: str
    last_seen: str


class PresignedMultipartPartResponse(WireResponse):
    part_number: int
    url: str


class PresignedMultipartResponse(WireResponse):
    upload_id: str
    parts: list[PresignedMultipartPartResponse]
    part_size: int | None = None


class UploadInitResponse(WireResponse):
    upload_id: str
    method: Literal["PUT", "POST"]
    url: str
    headers: dict[str, str]
    expires_in: int
    multipart: PresignedMultipartResponse | None = None


UploadLifecycleStatus = Literal[
    "INITIALIZED",
    "UPLOADING",
    "UPLOADED",
    "VERIFYING",
    "ACCEPTED",
    "QUARANTINED",
    "REJECTED",
]


class UploadCompletionResponse(WireResponse):
    upload_id: str
    status: UploadLifecycleStatus
    verification_status: UploadLifecycleStatus
    sha256: str | None = None
    duplicate: bool | None = None
    blob_id: str | None = None
    occurrence_id: str | None = None
    rejection_reason: str | None = None
    artifact_entry_id: str | None = None
    availability: (
        Literal[
            "validating",
            "waiting_for_pair",
            "symbols_available",
            "identity_conflict",
            "no_debug_identity",
            "storage_unavailable",
        ]
        | None
    ) = None
    workspace_id: str | None = None
    version: str | None = None

    current_version: str | None = None
    version_conflict: bool = False


class ArtifactEntryResponse(WireResponse):
    id: str
    file_id: str
    workspace_id: str | None
    name: str
    version: str | None
    kind: Literal["pe", "pdb"]
    sha256: str
    size: int
    code_id: str | None
    debug_id: str | None
    availability: Literal[
        "validating",
        "waiting_for_pair",
        "symbols_available",
        "identity_conflict",
        "no_debug_identity",
        "storage_unavailable",
    ]
    source: Literal["api", "cli", "browser"]
    created_at: str


class ArtifactPageResponse(WireResponse):
    items: list[ArtifactEntryResponse]
    next_cursor: str | None


class OccurrenceVersionResponse(WireResponse):
    occurrence_id: str
    version: str | None
    updated_at: str


class BlobResponse(WireResponse):
    id: str
    sha256: str
    size: int
    dump_kind: Literal["user_minidump", "kernel", "unknown_binary"]
    verification_status: Literal[
        "initialized", "uploading", "uploaded", "verifying", "accepted", "quarantined", "rejected"
    ]
    uploaded_at: str
    expires_at: str | None
    deleted_at: str | None


AnalysisStatus = Literal[
    "UPLOADED",
    "VALIDATING",
    "INSPECTED",
    "MATCHING_SYMBOLS",
    "WAITING_FOR_SYMBOLS",
    "SYMBOLS_READY",
    "QUEUED",
    "ANALYZING",
    "NORMALIZING",
    "GROUPING",
    "COMPLETE",
    "PARTIAL",
    "FAILED",
    "REJECTED",
    "CANCELLED",
    "TIMEOUT",
    "OOM",
]


class AnalysisRunResponse(WireResponse):
    id: str
    status: AnalysisStatus
    quality_score: float | None
    started_at: str | None
    finished_at: str | None
    duration_ms: float | None
    error_code: str | None
    error_detail: str | None


class OccurrenceResponse(WireResponse):
    id: str
    workspace_id: str
    blob: BlobResponse
    version: str | None
    dump_timestamp: str | None
    reported_at: str | None
    occurred_at: str
    uploaded_at: str
    time_source: Literal["dump", "reported", "uploaded", "manual"]
    current_analysis: AnalysisRunResponse | None
    latest_attempt: AnalysisRunResponse | None
    group: GroupSummaryResponse | None


class OccurrenceListSummaryResponse(WireResponse):
    crash_type: Literal["crash", "hang", "unknown"]
    exception_code: str | None
    exception_name: str | None
    access_type: str | None
    fault_module: str | None
    top_function: str | None
    version: str | None


class OccurrenceListItemResponse(WireResponse):
    id: str
    version: str | None
    workspace_id: str
    occurred_at: str
    uploaded_at: str
    time_source: Literal["dump", "reported", "uploaded", "manual"]
    current_analysis: AnalysisRunResponse | None
    latest_attempt: AnalysisRunResponse | None
    summary: OccurrenceListSummaryResponse | None
    group: GroupSummaryResponse | None


class OccurrenceListPageResponse(WireResponse):
    items: list[OccurrenceListItemResponse]
    next_cursor: str | None


class PlatformAttentionResponse(WireResponse):
    in_progress: int
    latest_attempt_failed: int
    unclassified_crashes: int
    symbol_affected_occurrences: int


class PlatformWorkspaceSummaryResponse(WireResponse):
    workspace: WorkspaceResponse
    occurrence_count: int
    attention_count: int
    last_occurrence_at: str | None


class PlatformOverviewResponse(WireResponse):
    window_start: str
    window_end: str
    workspace_count: int
    attention: PlatformAttentionResponse
    workspaces: list[PlatformWorkspaceSummaryResponse]
    recent_occurrences: list[OccurrenceListItemResponse]


class ReprocessResponse(WireResponse):
    demand_id: str
    status: str
    created: bool


class VersionCountResponse(WireResponse):
    version: str | None
    count: int


class OverviewResponse(WireResponse):
    window_start: str
    window_end: str
    crash_occurrences: int
    exact_groups: int
    unclassified: int
    versions: list[VersionCountResponse]
    top_groups: list[GroupSummaryResponse]
    symbol_completeness: float
    failure_rate: float
    average_analysis_duration_ms: float
    hang_captures: int
    unknown_captures: int
    rejected_uploads: int


class SourceContextResponse(WireResponse):
    pre: list[str] = Field(default_factory=list)
    line: str | None = None
    post: list[str] = Field(default_factory=list)


class CanonicalFrameResponse(WireResponse):
    index: int
    instruction_addr: str
    module_index: int | None = None
    physical_frame_index: int | None = None
    unwind_method: Literal[
        "context", "call_frame_info", "cfi_scan", "frame_pointer", "scan", "prewalked", "unknown"
    ] = "unknown"
    module: str | None = None
    module_debug_id: str | None = None
    relative_addr: str | None = None
    function: str | None = None
    function_raw: str | None = None
    function_normalized: str | None = None
    function_offset: int | None = None
    file: str | None = None
    line: int | None = None
    trust: Literal["context", "cfi", "frame_pointer", "scan", "unknown"]
    inline: bool | None = None
    in_app: bool
    source_context: SourceContextResponse | None = None


class VersionDistributionResponse(WireResponse):
    version: str | None
    count: int


class GroupDetailResponse(GroupSummaryResponse):
    representative_stack: list[CanonicalFrameResponse]
    version_distribution: list[VersionDistributionResponse]
    occurrence_ids: list[str]


class SymbolHealthResponse(WireResponse):
    code_file: str | None
    debug_file: str | None
    code_id: str | None
    debug_id: str | None
    status: Literal["matched", "missing", "mismatch"]
    affected_occurrence_count: int
    first_seen: str
    last_seen: str
    occurrence_ids: list[str]


class BatchReprocessResponse(WireResponse):
    workspace_id: str
    affected_occurrence_count: int
    occurrence_ids: list[str]
    demand_ids: list[str]


class InAppRulesResponse(WireResponse):
    workspace_id: str
    version: int
    include_modules: list[str]
    exclude_modules: list[str]


class InAppRulesUpdateResponse(InAppRulesResponse):
    demand_ids: list[str]


class PresignedDownloadResponse(WireResponse):
    url: str
    expires_at: str
