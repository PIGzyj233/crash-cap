from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WireResponse(BaseModel):
    """Exact JSON representation returned by an ``/api/v1`` route."""

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


class SourceBundleDescriptorResponse(WireResponse):
    schema_version: Literal["1.0"]
    archive: str
    source_root: str
    strip_prefixes: list[str] = Field(default_factory=list)
    context_lines: int = 3


class SourceBundleIngestMetadataResponse(WireResponse):
    policy_version: Literal["source-bundle-v1.0"]
    entry_count: int
    source_entry_count: int
    uncompressed_size: int
    source_entries: list[str]


ArtifactKind = Literal["pe", "pdb", "source_bundle"]
ArtifactVerificationStatus = Literal[
    "pending",
    "verified",
    "rejected_fastlink",
    "pdb_mismatch",
    "pe_mismatch",
    "corrupted",
    "rejected_format",
]


class ArtifactResponse(WireResponse):
    id: str
    module_id: str | None
    kind: ArtifactKind
    logical_name: str
    sha256: str
    size: int
    code_id: str | None
    debug_id: str | None
    verification_status: ArtifactVerificationStatus
    ingest_metadata: SourceBundleIngestMetadataResponse | None
    created_at: str


class BuildModuleResponse(WireResponse):
    id: str
    code_file: str
    debug_file: str
    role: Literal["entrypoint", "owned", "dependency"]
    code_id: str | None
    debug_id: str | None
    in_app: bool
    artifact_count: int
    missing_occurrence_count: int


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
    first_build_id: str | None
    last_build_id: str | None


class BuildResponse(WireResponse):
    id: str
    workspace_id: str
    version: str
    build_number: str | None
    commit_sha: str | None
    channel: str | None
    architecture: Literal["x86_64"]
    toolchain: str | None
    producer: Literal["msvc", "clang-cl", "crashpad"] | None
    producer_build_id: str | None
    manifest_object_key: str | None
    manifest_schema_version: Literal["1.0", "2.0"] | None
    source_bundle_config: SourceBundleDescriptorResponse | None
    identity_mode: Literal["legacy", "content_v1"]
    fingerprint_version: Literal["build-content-v1"] | None
    content_fingerprint: str | None
    sealed_at: str | None
    created_at: str
    modules: list[BuildModuleResponse]
    artifacts: list[ArtifactResponse]
    groups: list[GroupSummaryResponse]


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


class ProducerResponse(WireResponse):
    producer: Literal["msvc", "clang-cl", "crashpad"]
    status: Literal["supported", "experimental"]
    artifact_format: str
    fixture_suite: str | None
    gate: str


class ArtifactProducerResponse(ProducerResponse):
    publication_contracts: list[Literal["1.0"]]
    minimum_client_version: str
    build_publications_enabled: bool


class MissingArtifactResponse(WireResponse):
    module_id: str
    kind: Literal["pe", "pdb"]
    logical_name: str


class RejectedArtifactResponse(WireResponse):
    artifact_id: str
    logical_name: str
    status: ArtifactVerificationStatus


class BuildCiStatusResponse(WireResponse):
    build_id: str
    manifest_schema_version: Literal["1.0", "2.0"] | None
    producer: Literal["msvc", "clang-cl", "crashpad"] | None
    producer_status: Literal["supported", "experimental", "unregistered"]
    manifest_present: bool
    module_count: int
    missing_artifacts: list[MissingArtifactResponse]
    rejected_artifacts: list[RejectedArtifactResponse]
    source_bundle_status: Literal["not_declared", "verified", "pending", "missing_or_rejected"]
    ready: bool


class BuildPublicationSummaryResponse(WireResponse):
    id: str
    workspace_id: str
    build_id: str
    origin: Literal["local", "ci"]
    client_publication_id: str
    client_version: str
    git_revision: str | None
    git_worktree_state: Literal["clean", "dirty", "unknown"]
    created_at: str
    last_seen_at: str


class ArtifactExpectationResponse(WireResponse):
    module_id: str
    module_code_file: str
    kind: Literal["pe", "pdb"]
    logical_name: str
    size: int
    sha256: str
    status: Literal["missing", "uploading", "verifying", "verified", "rejected"]
    artifact_id: str | None
    upload_id: str | None
    rejection_reason: str | None


class BuildPublicationStatusResponse(WireResponse):
    publication: BuildPublicationSummaryResponse | None
    publications: list[BuildPublicationSummaryResponse]
    build_id: str
    identity_mode: Literal["content_v1"]
    fingerprint_version: Literal["build-content-v1"]
    content_fingerprint: str
    status: Literal["registered", "uploading", "verifying", "ready", "rejected"]
    sealed_at: str | None
    expected_artifacts: list[ArtifactExpectationResponse]
    missing_artifacts: list[ArtifactExpectationResponse]
    rejected_artifacts: list[ArtifactExpectationResponse]
    ready: bool


class QueuedTaskResponse(WireResponse):
    status: Literal["QUEUED"]
    attempt_id: str
    created: bool


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
ResolutionMethod = Literal["reported", "auto_unique", "manual", "ambiguous", "unresolved"]


class AnalysisRunResponse(WireResponse):
    id: str
    status: AnalysisStatus
    resolution_method: ResolutionMethod
    resolved_build_id: str | None
    quality_score: float | None
    started_at: str | None
    finished_at: str | None
    duration_ms: float | None
    error_code: str | None


class OccurrenceResponse(WireResponse):
    id: str
    workspace_id: str
    blob: BlobResponse
    reported_build_id: str | None
    dump_timestamp: str | None
    reported_at: str | None
    occurred_at: str
    uploaded_at: str
    time_source: Literal["dump", "reported", "uploaded", "manual"]
    current_analysis: AnalysisRunResponse | None
    latest_attempt: AnalysisRunResponse | None
    group: GroupSummaryResponse | None


class ReprocessResponse(AnalysisRunResponse):
    created: bool


class RetryDispatchResponse(WireResponse):
    run_id: str
    status: AnalysisStatus
    attempt_id: str
    dispatch_state: Literal["legacy", "pending", "reopened", "active", "terminal"]


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


class BuildDistributionResponse(WireResponse):
    build_id: str
    version: str
    count: int


class GroupDetailResponse(GroupSummaryResponse):
    representative_stack: list[CanonicalFrameResponse]
    build_distribution: list[BuildDistributionResponse]
    occurrence_ids: list[str]


class SymbolHealthResponse(WireResponse):
    build_id: str | None
    module_id: str | None
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
    created_run_count: int
    occurrence_ids: list[str]
    run_ids: list[str]


class InAppRulesResponse(WireResponse):
    workspace_id: str
    version: int
    include_modules: list[str]
    exclude_modules: list[str]


class InAppRulesUpdateResponse(InAppRulesResponse):
    created_run_count: int
    run_ids: list[str] | None = None


class PresignedDownloadResponse(WireResponse):
    url: str
    expires_at: str
