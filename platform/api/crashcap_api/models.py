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
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .analysis_states import ANALYSIS_STATES, CURRENT_ELIGIBLE_STATES


def utcnow() -> datetime:
    return datetime.now(UTC)


JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")
IDENTITY_INT = BigInteger().with_variant(Integer(), "sqlite")

UPLOAD_STATUSES = frozenset(
    {"INITIALIZED", "UPLOADING", "UPLOADED", "VERIFYING", "ACCEPTED", "QUARANTINED", "REJECTED"}
)
ANALYSIS_STATUSES = ANALYSIS_STATES
CURRENT_ELIGIBLE_STATUSES = CURRENT_ELIGIBLE_STATES
TASK_TYPES = frozenset(
    {"verify_upload", "ingest_artifact", "reindex_symbols", "analyze_occurrence"}
)
TASK_INTENT_STATES = frozenset({"pending", "publishing", "published", "dead"})
TASK_EXECUTION_OUTCOMES = frozenset({"idle", "running", "succeeded", "failed", "dead"})


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
        CheckConstraint("in_app_rule_version >= 0", name="ck_workspaces_in_app_rule_version"),
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
    in_app_rules: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        default=lambda: {"include_modules": [], "exclude_modules": []},
        server_default=text('\'{"include_modules":[],"exclude_modules":[]}\''),
    )
    in_app_rule_version: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class Build(Base):
    __tablename__ = "builds"
    __table_args__ = (
        CheckConstraint("architecture = 'x86_64'", name="ck_builds_architecture"),
        CheckConstraint(
            "producer IS NULL OR producer IN ('msvc', 'clang-cl', 'crashpad')",
            name="ck_builds_producer",
        ),
        UniqueConstraint(
            "workspace_id", "producer", "producer_build_id", name="uq_builds_workspace_producer_id"
        ),
        UniqueConstraint(
            "workspace_id",
            "fingerprint_version",
            "content_fingerprint",
            name="uq_builds_workspace_content_fingerprint",
        ),
        CheckConstraint(
            "identity_mode IN ('legacy', 'content_v1')", name="ck_builds_identity_mode"
        ),
        CheckConstraint(
            "(identity_mode = 'legacy' AND fingerprint_version IS NULL "
            "AND content_fingerprint IS NULL AND sealed_at IS NULL) OR "
            "(identity_mode = 'content_v1' AND fingerprint_version = 'build-content-v1' "
            "AND content_fingerprint IS NOT NULL)",
            name="ck_builds_content_identity",
        ),
        CheckConstraint(
            "content_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_builds_content_fingerprint",
        ).ddl_if(dialect="postgresql"),
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
    producer: Mapped[str | None] = mapped_column(Text)
    producer_build_id: Mapped[str | None] = mapped_column(Text)
    manifest_object_key: Mapped[str | None] = mapped_column(Text)
    manifest_schema_version: Mapped[str | None] = mapped_column(Text)
    source_bundle_config: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    identity_mode: Mapped[str] = mapped_column(
        Text, default="legacy", server_default=text("'legacy'")
    )
    fingerprint_version: Mapped[str | None] = mapped_column(Text)
    content_fingerprint: Mapped[str | None] = mapped_column(CHAR(64))
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class BuildModule(Base):
    __tablename__ = "build_modules"
    __table_args__ = (
        CheckConstraint(
            "role IN ('entrypoint', 'owned', 'dependency')", name="ck_build_modules_role"
        ),
        UniqueConstraint("build_id", "id", name="uq_build_modules_build_id_id"),
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


class BuildPublication(Base):
    __tablename__ = "build_publications"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "origin",
            "client_publication_id",
            name="uq_build_publications_client_identity",
        ),
        CheckConstraint("origin IN ('local', 'ci')", name="ck_build_publications_origin"),
        CheckConstraint(
            "git_worktree_state IN ('clean', 'dirty', 'unknown')",
            name="ck_build_publications_git_state",
        ),
        Index("ix_build_publications_build_created", "build_id", text("created_at DESC")),
        Index(
            "ix_build_publications_workspace_created",
            "workspace_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    build_id: Mapped[str] = mapped_column(ForeignKey("builds.id"), nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    client_publication_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_version: Mapped[str] = mapped_column(Text, nullable=False)
    git_revision: Mapped[str | None] = mapped_column(Text)
    git_worktree_state: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class BuildArtifactExpectation(Base):
    __tablename__ = "build_artifact_expectations"
    __table_args__ = (
        CheckConstraint("kind IN ('pe', 'pdb')", name="ck_build_artifact_expectations_kind"),
        CheckConstraint("size > 0", name="ck_build_artifact_expectations_size"),
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="ck_build_artifact_expectations_sha256"
        ).ddl_if(dialect="postgresql"),
        UniqueConstraint(
            "build_id",
            "kind",
            "normalized_name",
            name="uq_build_artifact_expectations_logical_name",
        ),
        ForeignKeyConstraint(
            ["build_id", "module_id"],
            ["build_modules.build_id", "build_modules.id"],
            name="fk_build_artifact_expectations_build_module",
        ),
    )

    build_id: Mapped[str] = mapped_column(ForeignKey("builds.id"), primary_key=True)
    module_id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    logical_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
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
    ingest_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
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
        UniqueConstraint("id", "workspace_id", name="uq_occurrences_id_workspace"),
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
        CheckConstraint(
            "assembly_mode IN ('legacy', 'shadow', 'core-final')",
            name="ck_analysis_runs_assembly_mode",
        ),
        CheckConstraint(
            "winner_generation IS NULL OR winner_generation > 0",
            name="ck_analysis_runs_winner_generation",
        ),
        UniqueConstraint("id", "occurrence_id", name="uq_analysis_runs_id_occurrence"),
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
    inspect_object_key: Mapped[str | None] = mapped_column(Text)
    analysis_context: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    assembly_mode: Mapped[str] = mapped_column(
        Text, default="legacy", server_default=text("'legacy'")
    )
    winner_attempt_id: Mapped[str | None] = mapped_column(ForeignKey("task_intents.attempt_id"))
    winner_generation: Mapped[int | None] = mapped_column(BigInteger)
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
        CheckConstraint(
            "status IN ('open', 'resolved', 'ignored')", name="ck_missing_symbols_status"
        ),
        CheckConstraint("affected_occurrence_count >= 0", name="ck_missing_symbols_affected_count"),
        UniqueConstraint("id", name="uq_missing_symbols_id"),
        UniqueConstraint(
            "workspace_id",
            "identity_key",
            name="uq_missing_symbols_workspace_identity",
        ),
        UniqueConstraint("id", "workspace_id", name="uq_missing_symbols_id_workspace"),
    )

    id: Mapped[str | None] = mapped_column(Text)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    identity_key: Mapped[str | None] = mapped_column(Text)
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

    # The original table deliberately had no physical primary key.  The
    # projection revision supplies a stable identity key for every new/adopted
    # row while old nullable rows remain readable during the rollback window.
    __mapper_args__ = {"primary_key": [workspace_id, identity_key]}


class MissingSymbolOccurrence(Base):
    __tablename__ = "missing_symbol_occurrences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["missing_symbol_id", "workspace_id"],
            ["missing_symbols.id", "missing_symbols.workspace_id"],
            name="fk_missing_symbol_occurrences_symbol_workspace",
        ),
        ForeignKeyConstraint(
            ["occurrence_id", "workspace_id"],
            ["occurrences.id", "occurrences.workspace_id"],
            name="fk_missing_symbol_occurrences_occurrence_workspace",
        ),
        ForeignKeyConstraint(
            ["analysis_run_id", "occurrence_id"],
            ["analysis_runs.id", "analysis_runs.occurrence_id"],
            name="fk_missing_symbol_occurrences_run_occurrence",
        ),
        CheckConstraint(
            "reason IN ('missing_pe', 'missing_pdb', 'pdb_mismatch', 'pe_mismatch')",
            name="ck_missing_symbol_occurrences_reason",
        ),
        Index("ix_missing_symbol_occurrences_workspace", "workspace_id"),
        Index("ix_missing_symbol_occurrences_occurrence", "occurrence_id"),
        Index("ix_missing_symbol_occurrences_run", "analysis_run_id"),
        Index(
            "ix_missing_symbol_occurrences_workspace_symbol_occurrence",
            "workspace_id",
            "missing_symbol_id",
            "occurrence_id",
        ),
    )

    missing_symbol_id: Mapped[str] = mapped_column(Text, primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    code_file: Mapped[str | None] = mapped_column(Text)
    debug_file: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class SymbolProjectionState(Base):
    """Durable proof that one Current Analysis was projected, even if its set is empty."""

    __tablename__ = "symbol_projection_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["occurrence_id", "workspace_id"],
            ["occurrences.id", "occurrences.workspace_id"],
            name="fk_symbol_projection_states_occurrence_workspace",
        ),
        ForeignKeyConstraint(
            ["analysis_run_id", "occurrence_id"],
            ["analysis_runs.id", "analysis_runs.occurrence_id"],
            name="fk_symbol_projection_states_run_occurrence",
        ),
        CheckConstraint("missing_count >= 0", name="ck_symbol_projection_states_missing_count"),
        CheckConstraint(
            "source IN ('promotion', 'backfill')", name="ck_symbol_projection_states_source"
        ),
        Index("ix_symbol_projection_states_workspace_run", "workspace_id", "analysis_run_id"),
    )

    occurrence_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    identity_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    missing_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    projected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class SymbolProjectionCheckpoint(Base):
    __tablename__ = "symbol_projection_checkpoints"
    __table_args__ = (
        CheckConstraint("scanned_count >= 0", name="ck_symbol_projection_checkpoints_scanned"),
        CheckConstraint("projected_count >= 0", name="ck_symbol_projection_checkpoints_projected"),
        CheckConstraint("gap_count >= 0", name="ck_symbol_projection_checkpoints_gap"),
    )

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    cursor_occurrence_id: Mapped[str | None] = mapped_column(Text)
    scanned_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    projected_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    gap_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class SymbolProjectionGap(Base):
    __tablename__ = "symbol_projection_gaps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["occurrence_id", "workspace_id"],
            ["occurrences.id", "occurrences.workspace_id"],
            name="fk_symbol_projection_gaps_occurrence_workspace",
        ),
        CheckConstraint("attempt_count > 0", name="ck_symbol_projection_gaps_attempt_count"),
        Index("ix_symbol_projection_gaps_unresolved", "resolved_at", "occurrence_id"),
    )

    occurrence_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_run_id: Mapped[str | None] = mapped_column(Text)
    result_object_key: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskIntent(Base):
    __tablename__ = "task_intents"
    __table_args__ = (
        UniqueConstraint("task_type", "logical_key", name="uq_task_intents_type_logical_key"),
        CheckConstraint(
            "schema_version = '1.0'",
            name="ck_task_intents_schema_version",
        ),
        CheckConstraint(
            "task_type IN ('verify_upload', 'ingest_artifact', 'reindex_symbols', "
            "'analyze_occurrence')",
            name="ck_task_intents_type",
        ),
        CheckConstraint(
            "queue IN ('verify', 'ingest', 'dump-small', 'dump-large')",
            name="ck_task_intents_queue",
        ),
        CheckConstraint(
            "state IN ('pending', 'publishing', 'published', 'dead')",
            name="ck_task_intents_state",
        ),
        CheckConstraint("relay_generation >= 0", name="ck_task_intents_relay_generation"),
        CheckConstraint("delivery_attempts >= 0", name="ck_task_intents_delivery_attempts"),
        Index("ix_task_intents_due", "state", "due_at"),
        Index("ix_task_intents_relay_lease", "state", "relay_lease_until"),
        Index("ix_task_intents_target", "task_type", "target_type", "target_id"),
    )

    attempt_id: Mapped[str] = mapped_column(Text, primary_key=True)
    schema_version: Mapped[str] = mapped_column(Text, default="1.0", server_default=text("'1.0'"))
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    queue: Mapped[str] = mapped_column(Text, nullable=False)
    logical_key: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    request_id: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, default="pending", server_default=text("'pending'"))
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    relay_owner: Mapped[str | None] = mapped_column(Text)
    relay_generation: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    relay_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class TaskExecution(Base):
    __tablename__ = "task_executions"
    __table_args__ = (
        CheckConstraint(
            "task_type IN ('verify_upload', 'ingest_artifact', 'reindex_symbols', "
            "'analyze_occurrence')",
            name="ck_task_executions_type",
        ),
        CheckConstraint("generation >= 0", name="ck_task_executions_generation"),
        CheckConstraint(
            "outcome IN ('idle', 'running', 'succeeded', 'failed', 'dead')",
            name="ck_task_executions_outcome",
        ),
        Index("ix_task_executions_lease", "outcome", "lease_until"),
    )

    task_type: Mapped[str] = mapped_column(Text, primary_key=True)
    logical_key: Mapped[str] = mapped_column(Text, primary_key=True)
    active_attempt_id: Mapped[str] = mapped_column(
        ForeignKey("task_intents.attempt_id"), nullable=False
    )
    generation: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    owner_id: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(Text, default="idle", server_default=text("'idle'"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


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
    rejection_reason: Mapped[str | None] = mapped_column(Text)
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
