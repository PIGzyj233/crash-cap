from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    REAL,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")
IDENTITY_INT = BigInteger().with_variant(Integer(), "sqlite")

UPLOAD_STATUSES = frozenset(
    {"INITIALIZED", "UPLOADING", "UPLOADED", "VERIFYING", "ACCEPTED", "QUARANTINED", "REJECTED"}
)
ANALYSIS_STATUSES = frozenset(
    {
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
    }
)
CURRENT_ELIGIBLE_STATUSES = frozenset({"COMPLETE", "PARTIAL"})


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("name", name="uq_workspaces_name"),
        CheckConstraint("platform = 'windows'", name="ck_workspaces_platform"),
        CheckConstraint("default_architecture = 'x86_64'", name="ck_workspaces_architecture"),
        CheckConstraint("retention_days > 0", name="ck_workspaces_retention_days"),
        CheckConstraint("symbol_inventory_version >= 0", name="ck_workspaces_symbol_inventory"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text, default="windows", server_default=text("'windows'"))
    default_architecture: Mapped[str] = mapped_column(
        Text, default="x86_64", server_default=text("'x86_64'")
    )
    retention_days: Mapped[int] = mapped_column(Integer, default=180, server_default=text("180"))
    symbol_inventory_version: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class Build(Base):
    __tablename__ = "builds"
    __table_args__ = (
        CheckConstraint("architecture = 'x86_64'", name="ck_builds_architecture"),
        Index("ix_builds_workspace_created_at", "workspace_id", text("created_at DESC")),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    build_number: Mapped[str | None] = mapped_column(Text)
    commit_sha: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(Text)
    architecture: Mapped[str] = mapped_column(
        Text, default="x86_64", server_default=text("'x86_64'")
    )
    toolchain: Mapped[str | None] = mapped_column(Text)
    manifest_object_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class BuildModule(Base):
    __tablename__ = "build_modules"
    __table_args__ = (
        CheckConstraint(
            "role IN ('entrypoint', 'owned', 'dependency')", name="ck_build_modules_role"
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    build_id: Mapped[str] = mapped_column(ForeignKey("builds.id"), nullable=False)
    code_file: Mapped[str] = mapped_column(Text, nullable=False)
    debug_file: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    code_id: Mapped[str | None] = mapped_column(Text)
    debug_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint("kind IN ('pe', 'pdb', 'source_bundle')", name="ck_artifacts_kind"),
        CheckConstraint(
            "verification_status IN ('pending', 'verified', 'rejected_fastlink', "
            "'pdb_mismatch', 'pe_mismatch', 'corrupted', 'rejected_format')",
            name="ck_artifacts_verification_status",
        ),
        CheckConstraint("size >= 0", name="ck_artifacts_size"),
        CheckConstraint("sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_artifacts_sha256").ddl_if(
            dialect="postgresql"
        ),
        Index("ix_artifacts_debug_id", "debug_id"),
        Index("ix_artifacts_code_id", "code_id"),
        Index("ix_artifacts_sha256", "sha256"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    build_id: Mapped[str] = mapped_column(ForeignKey("builds.id"), nullable=False)
    module_id: Mapped[str | None] = mapped_column(ForeignKey("build_modules.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    logical_name: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    code_id: Mapped[str | None] = mapped_column(Text)
    debug_id: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(
        Text, default="pending", server_default=text("'pending'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class DumpBlob(Base):
    __tablename__ = "dump_blobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sha256", name="uq_dump_blobs_workspace_sha256"),
        CheckConstraint("size >= 0", name="ck_dump_blobs_size"),
        CheckConstraint("dump_kind = 'user_minidump'", name="ck_dump_blobs_kind"),
        CheckConstraint(
            "verification_status IN "
            "('INITIALIZED', 'UPLOADING', 'UPLOADED', 'VERIFYING', "
            "'ACCEPTED', 'QUARANTINED', 'REJECTED')",
            name="ck_dump_blobs_verification_status",
        ),
        CheckConstraint("sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_dump_blobs_sha256").ddl_if(
            dialect="postgresql"
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    dump_kind: Mapped[str] = mapped_column(
        Text, default="user_minidump", server_default=text("'user_minidump'")
    )
    architecture: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(
        Text, default="VERIFYING", server_default=text("'VERIFYING'")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Occurrence(Base):
    __tablename__ = "occurrences"
    __table_args__ = (
        UniqueConstraint("dump_blob_id", name="uq_occurrences_dump_blob_id"),
        CheckConstraint(
            "time_source IN ('dump', 'reported', 'uploaded', 'manual')",
            name="ck_occurrences_time_source",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    dump_blob_id: Mapped[str] = mapped_column(ForeignKey("dump_blobs.id"), nullable=False)
    reported_build_id: Mapped[str | None] = mapped_column(ForeignKey("builds.id"))
    current_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_runs.id", use_alter=True, name="fk_occurrences_current_run_id")
    )
    dump_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_analysis_runs_idempotency_key"),
        CheckConstraint(
            "resolution_method IN ('reported', 'auto_unique', 'manual', 'ambiguous', 'unresolved')",
            name="ck_analysis_runs_resolution_method",
        ),
        CheckConstraint("schema_version = '1.0'", name="ck_analysis_runs_schema_version"),
        CheckConstraint(
            "grouping_version = 'group-v1.0'", name="ck_analysis_runs_grouping_version"
        ),
        CheckConstraint(
            "normalization_version = 'norm-v1.0'", name="ck_analysis_runs_normalization_version"
        ),
        CheckConstraint("symbol_inventory_version >= 0", name="ck_analysis_runs_symbol_inventory"),
        CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0.0 AND quality_score <= 1.0)",
            name="ck_analysis_runs_quality_score",
        ),
        CheckConstraint(
            "status IN ('UPLOADED', 'VALIDATING', 'INSPECTED', 'MATCHING_SYMBOLS', "
            "'WAITING_FOR_SYMBOLS', 'SYMBOLS_READY', 'QUEUED', 'ANALYZING', "
            "'NORMALIZING', 'GROUPING', 'COMPLETE', 'PARTIAL', 'FAILED', "
            "'REJECTED', 'CANCELLED', 'TIMEOUT', 'OOM')",
            name="ck_analysis_runs_status",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[0-9a-fA-F]{64}$'",
            name="ck_analysis_runs_idempotency_key",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(ForeignKey("occurrences.id"), nullable=False)
    run_spec: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    reported_build_id: Mapped[str | None] = mapped_column(ForeignKey("builds.id"))
    resolved_build_id: Mapped[str | None] = mapped_column(ForeignKey("builds.id"))
    resolution_method: Mapped[str] = mapped_column(Text, default="unresolved", nullable=False)
    resolution_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    core_version: Mapped[str] = mapped_column(Text, nullable=False)
    core_image_digest: Mapped[str] = mapped_column(Text, nullable=False)
    symbolicator_version: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, default="1.0", server_default=text("'1.0'"))
    grouping_version: Mapped[str] = mapped_column(
        Text, default="group-v1.0", server_default=text("'group-v1.0'")
    )
    normalization_version: Mapped[str] = mapped_column(
        Text, default="norm-v1.0", server_default=text("'norm-v1.0'")
    )
    symbol_inventory_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    quality_score: Mapped[float | None] = mapped_column(REAL)
    result_object_key: Mapped[str | None] = mapped_column(Text)
    raw_object_prefix: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)


class AnalysisSummary(Base):
    __tablename__ = "analysis_summaries"
    __table_args__ = (
        CheckConstraint(
            "crash_type IN ('crash', 'hang', 'unknown')", name="ck_analysis_summaries_crash_type"
        ),
        CheckConstraint(
            "symbol_coverage IS NULL OR (symbol_coverage >= 0.0 AND symbol_coverage <= 1.0)",
            name="ck_analysis_summaries_symbol_coverage",
        ),
        CheckConstraint(
            "unwind_reliability IS NULL OR "
            "(unwind_reliability >= 0.0 AND unwind_reliability <= 1.0)",
            name="ck_analysis_summaries_unwind_reliability",
        ),
        CheckConstraint(
            "artifact_completeness IS NULL OR "
            "(artifact_completeness >= 0.0 AND artifact_completeness <= 1.0)",
            name="ck_analysis_summaries_artifact_completeness",
        ),
        Index("ix_analysis_summaries_exact_fingerprint", "exact_fingerprint"),
        Index("ix_analysis_summaries_exception_fault_module", "exception_code", "fault_module"),
    )

    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(ForeignKey("occurrences.id"), nullable=False)
    resolved_build_id: Mapped[str | None] = mapped_column(ForeignKey("builds.id"))
    version: Mapped[str | None] = mapped_column(Text)
    exception_code: Mapped[str | None] = mapped_column(Text)
    exception_name: Mapped[str | None] = mapped_column(Text)
    access_type: Mapped[str | None] = mapped_column(Text)
    crash_address: Mapped[str | None] = mapped_column(Text)
    crashing_thread_id: Mapped[int | None] = mapped_column(BigInteger)
    fault_module: Mapped[str | None] = mapped_column(Text)
    top_function: Mapped[str | None] = mapped_column(Text)
    top_source_file: Mapped[str | None] = mapped_column(Text)
    top_source_line: Mapped[int | None] = mapped_column(Integer)
    symbol_coverage: Mapped[float | None] = mapped_column(REAL)
    unwind_reliability: Mapped[float | None] = mapped_column(REAL)
    artifact_completeness: Mapped[float | None] = mapped_column(REAL)
    exact_fingerprint: Mapped[str | None] = mapped_column(Text)
    family_fingerprint: Mapped[str | None] = mapped_column(Text)
    crashing_frames: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON_TYPE)
    crash_type: Mapped[str] = mapped_column(Text, nullable=False)


class CrashGroup(Base):
    __tablename__ = "crash_groups"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "group_type",
            "fingerprint",
            name="uq_crash_groups_workspace_type_fingerprint",
        ),
        CheckConstraint("group_type = 'exact'", name="ck_crash_groups_type"),
        CheckConstraint(
            "status IN ('open', 'investigating', 'fixed', 'ignored')",
            name="ck_crash_groups_status",
        ),
        CheckConstraint("occurrence_count >= 0", name="ck_crash_groups_occurrence_count"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    group_type: Mapped[str] = mapped_column(Text, default="exact", server_default=text("'exact'"))
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    representative_run_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_runs.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="open", server_default=text("'open'"))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    first_build_id: Mapped[str | None] = mapped_column(ForeignKey("builds.id"))
    last_build_id: Mapped[str | None] = mapped_column(ForeignKey("builds.id"))
    owner: Mapped[str | None] = mapped_column(Text)
    issue_url: Mapped[str | None] = mapped_column(Text)


class GroupMembership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (CheckConstraint("similarity = 1.0", name="ck_group_memberships_similarity"),)

    occurrence_id: Mapped[str] = mapped_column(ForeignKey("occurrences.id"), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("crash_groups.id"), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False)
    similarity: Mapped[float] = mapped_column(REAL, default=1.0, server_default=text("1.0"))
    grouping_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class GroupMembershipHistory(Base):
    __tablename__ = "group_membership_history"
    __table_args__ = (
        CheckConstraint(
            "action IN ('assign', 'move', 'unclassify')",
            name="ck_group_membership_history_action",
        ),
        CheckConstraint("similarity = 1.0", name="ck_group_membership_history_similarity"),
        Index("ix_group_membership_history_occurrence_recorded", "occurrence_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(IDENTITY_INT, primary_key=True, autoincrement=True)
    occurrence_id: Mapped[str] = mapped_column(ForeignKey("occurrences.id"), nullable=False)
    previous_group_id: Mapped[str | None] = mapped_column(ForeignKey("crash_groups.id"))
    group_id: Mapped[str | None] = mapped_column(ForeignKey("crash_groups.id"))
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    similarity: Mapped[float] = mapped_column(REAL, default=1.0, server_default=text("1.0"))
    grouping_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class MissingSymbol(Base):
    __tablename__ = "missing_symbols"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "debug_id",
            "code_id",
            name="uq_missing_symbols_workspace_debug_code",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "status IN ('open', 'resolved', 'ignored')", name="ck_missing_symbols_status"
        ),
        CheckConstraint("affected_occurrence_count >= 0", name="ck_missing_symbols_affected_count"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    code_file: Mapped[str | None] = mapped_column(Text)
    code_id: Mapped[str | None] = mapped_column(Text)
    debug_file: Mapped[str | None] = mapped_column(Text)
    debug_id: Mapped[str | None] = mapped_column(Text)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    affected_occurrence_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(Text, default="open", server_default=text("'open'"))

    __mapper_args__ = {"primary_key": [workspace_id, debug_id, code_id]}


class Upload(Base):
    __tablename__ = "uploads"
    __table_args__ = (
        UniqueConstraint("object_key", name="uq_uploads_object_key"),
        CheckConstraint("declared_length >= 0", name="ck_uploads_declared_length"),
        CheckConstraint(
            "verified_length IS NULL OR verified_length >= 0", name="ck_uploads_verified_length"
        ),
        CheckConstraint(
            "file_kind IN ('dmp', 'pe', 'pdb', 'source_bundle')", name="ck_uploads_file_kind"
        ),
        CheckConstraint(
            "verification_status IN "
            "('INITIALIZED', 'UPLOADING', 'UPLOADED', 'VERIFYING', "
            "'ACCEPTED', 'QUARANTINED', 'REJECTED')",
            name="ck_uploads_verification_status",
        ),
        CheckConstraint(
            "client_sha256_hint IS NULL OR client_sha256_hint ~ '^[0-9a-fA-F]{64}$'",
            name="ck_uploads_client_sha256_hint",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "verified_sha256 IS NULL OR verified_sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_uploads_verified_sha256",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    build_id: Mapped[str | None] = mapped_column(ForeignKey("builds.id"))
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    declared_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verified_length: Mapped[int | None] = mapped_column(BigInteger)
    client_sha256_hint: Mapped[str | None] = mapped_column(CHAR(64))
    verified_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    source_ip: Mapped[str | None] = mapped_column(Text)
    file_kind: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(
        Text, default="INITIALIZED", server_default=text("'INITIALIZED'")
    )
    capture_profile: Mapped[str | None] = mapped_column(Text)
    reported_build_id: Mapped[str | None] = mapped_column(ForeignKey("builds.id"))
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationLog(Base):
    __tablename__ = "operation_logs"
    __table_args__ = (CheckConstraint("actor = 'anonymous'", name="ck_operation_logs_actor"),)

    id: Mapped[int] = mapped_column(IDENTITY_INT, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"))
    actor: Mapped[str] = mapped_column(
        Text, default="anonymous", server_default=text("'anonymous'")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    request_id: Mapped[str | None] = mapped_column(Text)
    source_ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
