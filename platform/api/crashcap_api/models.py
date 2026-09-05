from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    REAL,
    BigInteger,
    Boolean,
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
    {
        "verify_upload",
        "analyze_frozen_run",
        "dispatch_workspace_role",
    }
)
TASK_INTENT_STATES = frozenset({"pending", "publishing", "published", "dead"})
TASK_EXECUTION_OUTCOMES = frozenset({"idle", "running", "succeeded", "failed", "dead"})


class Base(DeclarativeBase):
    pass


class CatalogWatermark(Base):
    __tablename__ = "catalog_watermark"
    __table_args__ = (CheckConstraint("id = 1 AND revision >= 0", name="ck_catalog_watermark"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class CatalogFile(Base):
    __tablename__ = "catalog_files"
    __table_args__ = (
        UniqueConstraint("kind", "raw_sha256", name="uq_catalog_files_content"),
        CheckConstraint("kind IN ('pe','pdb') AND raw_size > 0", name="ck_catalog_files_shape"),
        CheckConstraint("architecture IN ('x86_64','unknown')", name="ck_catalog_files_arch"),
        CheckConstraint("kind <> 'pe' OR code_id IS NOT NULL", name="ck_catalog_files_pe_identity"),
    )
    id: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    raw_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    raw_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    code_id: Mapped[str | None] = mapped_column(Text)
    debug_id: Mapped[str | None] = mapped_column(Text)
    architecture: Mapped[str] = mapped_column(Text, nullable=False)
    validator_version: Mapped[str] = mapped_column(Text, nullable=False)
    verification_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    verification_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class CatalogFileLocation(Base):
    __tablename__ = "catalog_file_locations"
    __table_args__ = (
        UniqueConstraint("object_key", name="uq_catalog_locations_object"),
        CheckConstraint(
            "payload_encoding IN ('identity','zstd-v1') AND payload_size > 0",
            name="ck_catalog_locations_payload",
        ),
        CheckConstraint("state IN ('available','unavailable')", name="ck_catalog_locations_state"),
        CheckConstraint(
            "retention_basis = 'platform_owned'",
            name="ck_catalog_locations_retention",
        ),
        Index("ix_catalog_locations_file", "file_id", "state"),
    )
    id: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("catalog_files.id"), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload_encoding: Mapped[str] = mapped_column(Text, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    payload_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    retention_basis: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="available")
    verification_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    verification_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class CatalogPair(Base):
    __tablename__ = "catalog_pairs"
    __table_args__ = (
        UniqueConstraint("pe_file_id", "pdb_file_id", name="uq_catalog_pairs_content"),
        CheckConstraint(
            "state IN ('active','withdrawn') AND qualification_version > 0",
            name="ck_catalog_pairs_qualification",
        ),
        CheckConstraint("architecture = 'x86_64'", name="ck_catalog_pairs_arch"),
    )
    id: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    pe_file_id: Mapped[str] = mapped_column(ForeignKey("catalog_files.id"), nullable=False)
    pdb_file_id: Mapped[str] = mapped_column(ForeignKey("catalog_files.id"), nullable=False)
    code_id: Mapped[str] = mapped_column(Text, nullable=False)
    debug_id: Mapped[str] = mapped_column(Text, nullable=False)
    architecture: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    qualification_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class CatalogPairOrigin(Base):
    __tablename__ = "catalog_pair_origins"
    __table_args__ = (
        UniqueConstraint(
            "origin_type", "origin_key", "pair_id", name="uq_catalog_origins_source_pair"
        ),
        CheckConstraint(
            "origin_type = 'upload'",
            name="ck_catalog_origins_type",
        ),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    pair_id: Mapped[str] = mapped_column(ForeignKey("catalog_pairs.id"), nullable=False)
    origin_type: Mapped[str] = mapped_column(Text, nullable=False)
    origin_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"))
    details: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class CatalogIdentityMembership(Base):
    __tablename__ = "catalog_identity_memberships"
    __table_args__ = (
        Index("ix_catalog_memberships_code", "code_id", "architecture"),
        Index("ix_catalog_memberships_debug", "debug_id", "architecture"),
    )
    pair_id: Mapped[str] = mapped_column(ForeignKey("catalog_pairs.id"), primary_key=True)
    code_id: Mapped[str] = mapped_column(Text, nullable=False)
    debug_id: Mapped[str] = mapped_column(Text, nullable=False)
    architecture: Mapped[str] = mapped_column(Text, nullable=False)


class CatalogPairReview(Base):
    __tablename__ = "catalog_pair_reviews"
    __table_args__ = (
        UniqueConstraint("pair_id", "qualification_version", name="uq_catalog_reviews_version"),
        UniqueConstraint("idempotency_key", name="uq_catalog_reviews_idempotency"),
        CheckConstraint(
            "state IN ('active','withdrawn') AND qualification_version > 1",
            name="ck_catalog_reviews_state",
        ),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    pair_id: Mapped[str] = mapped_column(ForeignKey("catalog_pairs.id"), nullable=False)
    qualification_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class CatalogChange(Base):
    __tablename__ = "catalog_changes"
    __table_args__ = (CheckConstraint("revision > 0", name="ck_catalog_changes_revision"),)
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    pair_id: Mapped[str | None] = mapped_column(ForeignKey("catalog_pairs.id"))
    file_id: Mapped[str | None] = mapped_column(ForeignKey("catalog_files.id"))
    code_id: Mapped[str | None] = mapped_column(Text)
    debug_id: Mapped[str | None] = mapped_column(Text)
    architecture: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[str] = mapped_column(Text, nullable=False)
    affects_selection: Mapped[bool] = mapped_column(Boolean, nullable=False)
    review_id: Mapped[str | None] = mapped_column(ForeignKey("catalog_pair_reviews.id"))
    details: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("name", name="uq_workspaces_name"),
        CheckConstraint("platform = 'windows'", name="ck_workspaces_platform"),
        CheckConstraint("default_architecture = 'x86_64'", name="ck_workspaces_architecture"),
        CheckConstraint("retention_days > 0", name="ck_workspaces_retention_days"),
        CheckConstraint("symbol_inventory_version >= 0", name="ck_workspaces_symbol_inventory"),
        CheckConstraint("in_app_rule_version >= 0", name="ck_workspaces_in_app_rule_version"),
        CheckConstraint("module_role_version >= 0", name="ck_workspaces_module_role_version"),
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
    module_role_version: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class WorkspaceModuleRole(Base):
    """Append-only, exact-identity role declarations owned by one Workspace."""

    __tablename__ = "workspace_module_roles"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_workspace_module_roles_version"),
        CheckConstraint("architecture = 'x86_64'", name="ck_workspace_module_roles_architecture"),
        CheckConstraint("role IN ('owned','dependency')", name="ck_workspace_module_roles_role"),
        CheckConstraint(
            "code_id ~ '^[0-9a-f]{9,24}$'", name="ck_workspace_module_roles_code_id"
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "debug_id ~ '^[0-9a-f]{33,40}$'", name="ck_workspace_module_roles_debug_id"
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_workspace_module_roles_identity_version",
            "workspace_id",
            "code_id",
            "debug_id",
            "architecture",
            text("version DESC"),
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), primary_key=True, nullable=False
    )
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    code_id: Mapped[str] = mapped_column(Text, nullable=False)
    debug_id: Mapped[str] = mapped_column(Text, nullable=False)
    architecture: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class DumpInspection(Base):
    __tablename__ = "dump_inspections"
    __table_args__ = (
        UniqueConstraint(
            "dump_blob_id",
            "inspector_version",
            "inspector_provenance",
            name="uq_dump_inspections_version",
        ),
        CheckConstraint("dump_size > 0", name="ck_dump_inspections_size"),
    )
    id: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    dump_blob_id: Mapped[str] = mapped_column(ForeignKey("dump_blobs.id"), nullable=False)
    inspector_version: Mapped[str] = mapped_column(Text, nullable=False)
    inspector_provenance: Mapped[str] = mapped_column(Text, nullable=False)
    dump_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    dump_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    object_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    modules: Mapped[list[dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalysisDemand(Base):
    __tablename__ = "auto_analysis_demands"
    __table_args__ = (
        UniqueConstraint("occurrence_id", name="uq_analysis_demands_occurrence"),
        ForeignKeyConstraint(
            ["occurrence_id", "workspace_id"], ["occurrences.id", "occurrences.workspace_id"]
        ),
        CheckConstraint(
            "generation >= 0 AND retry_attempt >= 0", name="ck_analysis_demands_counters"
        ),
        CheckConstraint(
            "planned_sequence >= 0 AND change_sequence >= planned_sequence",
            name="ck_analysis_demands_sequence",
        ),
        CheckConstraint("index_revision >= 0", name="ck_analysis_demands_revision"),
        CheckConstraint(
            "state IN ('preparing','coalescing','queued','running','updated','retained',"
            "'needs_review','retry_wait','retry_exhausted','cannot_recompute','paused')",
            name="ck_analysis_demands_state",
        ),
        Index("ix_analysis_demands_ready", "state", "not_before", "workspace_id", "id"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_id: Mapped[str] = mapped_column(Text, nullable=False)
    inspection_id: Mapped[str | None] = mapped_column(ForeignKey("dump_inspections.id"))
    state: Mapped[str] = mapped_column(Text, nullable=False, default="preparing")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    retry_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    change_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    planned_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    index_revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    first_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalysisDemandRestart(Base):
    __tablename__ = "analysis_demand_restarts"
    __table_args__ = (
        UniqueConstraint("demand_id", "idempotency_key", name="uq_analysis_demand_restart_request"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    demand_id: Mapped[str] = mapped_column(ForeignKey("auto_analysis_demands.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class DumpSymbolReference(Base):
    __tablename__ = "dump_symbol_references"
    __table_args__ = (
        CheckConstraint("module_index >= 0", name="ck_dump_symbol_references_index"),
        Index("ix_dump_symbol_references_code", "code_id", "occurrence_id"),
        Index("ix_dump_symbol_references_debug", "debug_id", "occurrence_id"),
    )
    occurrence_id: Mapped[str] = mapped_column(ForeignKey("occurrences.id"), primary_key=True)
    module_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[str] = mapped_column(ForeignKey("dump_inspections.id"), nullable=False)
    code_id: Mapped[str | None] = mapped_column(Text)
    debug_id: Mapped[str | None] = mapped_column(Text)
    architecture: Mapped[str] = mapped_column(Text, nullable=False)


class AnalysisDemandTarget(Base):
    __tablename__ = "analysis_demand_targets"
    __table_args__ = (
        CheckConstraint(
            "cause IN ('initial','symbol_refresh','role_change','engine_upgrade',"
            "'evidence_correction','manual')",
            name="ck_demand_targets_cause",
        ),
        CheckConstraint(
            "generation > 0 AND catalog_revision >= 0", name="ck_demand_targets_counters"
        ),
    )
    demand_id: Mapped[str] = mapped_column(ForeignKey("auto_analysis_demands.id"), primary_key=True)
    generation: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    inspection_id: Mapped[str] = mapped_column(ForeignKey("dump_inspections.id"), nullable=False)
    resolution_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    context_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    cause: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    catalog_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalysisEventCursor(Base):
    __tablename__ = "analysis_event_cursors"
    __table_args__ = (CheckConstraint("revision >= 0", name="ck_analysis_event_cursors_revision"),)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    after_occurrence_id: Mapped[str | None] = mapped_column(Text)


class DumpBlob(Base):
    __tablename__ = "dump_blobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sha256", name="uq_dump_blobs_workspace_sha256"),
        CheckConstraint("size >= 0", name="ck_dump_blobs_size"),
        CheckConstraint(
            "capture_profile IS NULL OR capture_profile IN "
            "('light-crash','rich-crash','hang','full-memory')",
            name="ck_dump_blobs_capture_profile",
        ),
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
    capture_profile: Mapped[str | None] = mapped_column(Text)
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
        Index(
            "ix_occurrences_workspace_occurred_id",
            "workspace_id",
            text("occurred_at DESC"),
            text("id DESC"),
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    dump_blob_id: Mapped[str] = mapped_column(ForeignKey("dump_blobs.id"), nullable=False)
    version: Mapped[str | None] = mapped_column(Text)
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
        UniqueConstraint(
            "demand_id",
            "demand_generation",
            "retry_attempt",
            name="uq_analysis_runs_demand_attempt",
        ),
        CheckConstraint(
            "(demand_id IS NULL AND demand_generation IS NULL AND retry_attempt IS NULL) OR "
            "(demand_id IS NOT NULL AND demand_generation > 0 AND retry_attempt >= 0)",
            name="ck_analysis_runs_demand_attempt",
        ),
        CheckConstraint("schema_version = '2.0'", name="ck_analysis_runs_schema_version"),
        CheckConstraint(
            "grouping_version = 'group-v1.1'",
            name="ck_analysis_runs_grouping_version",
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
            "assembly_mode = 'core-final'",
            name="ck_analysis_runs_assembly_mode",
        ),
        CheckConstraint(
            "winner_generation IS NULL OR winner_generation > 0",
            name="ck_analysis_runs_winner_generation",
        ),
        UniqueConstraint("id", "occurrence_id", name="uq_analysis_runs_id_occurrence"),
        Index(
            "ix_analysis_runs_occurrence_id_desc",
            "occurrence_id",
            text("id DESC"),
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(ForeignKey("occurrences.id"), nullable=False)
    demand_id: Mapped[str | None] = mapped_column(ForeignKey("auto_analysis_demands.id"))
    demand_generation: Mapped[int | None] = mapped_column(BigInteger)
    retry_attempt: Mapped[int | None] = mapped_column(Integer)
    run_spec: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    core_version: Mapped[str] = mapped_column(Text, nullable=False)
    core_image_digest: Mapped[str] = mapped_column(Text, nullable=False)
    symbolicator_version: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, default="2.0", server_default=text("'2.0'"))
    grouping_version: Mapped[str] = mapped_column(
        Text, default="group-v1.1", server_default=text("'group-v1.1'")
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
        Text, default="core-final", server_default=text("'core-final'")
    )
    winner_attempt_id: Mapped[str | None] = mapped_column(ForeignKey("task_intents.attempt_id"))
    winner_generation: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)


class AnalysisSchedulerState(Base):
    __tablename__ = "analysis_scheduler_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_analysis_scheduler_state_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_workspace_id: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class AnalysisExecutionSlot(Base):
    """Durable automatic-analysis capacity from planning through Run terminal state."""

    __tablename__ = "analysis_execution_slots"
    __table_args__ = (
        UniqueConstraint("claim_token", name="uq_analysis_execution_slots_claim"),
        UniqueConstraint("run_id", name="uq_analysis_execution_slots_run"),
        CheckConstraint(
            "state IN ('planning','executing')", name="ck_analysis_execution_slots_state"
        ),
        CheckConstraint(
            "(state = 'planning' AND run_id IS NULL) OR "
            "(state = 'executing' AND run_id IS NOT NULL)",
            name="ck_analysis_execution_slots_binding",
        ),
        Index("ix_analysis_execution_slots_lease", "state", "lease_until"),
    )

    demand_id: Mapped[str] = mapped_column(ForeignKey("auto_analysis_demands.id"), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    claim_token: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_runs.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class CurrentDecision(Base):
    """Immutable evidence-v1 decision for one terminal candidate Run."""

    __tablename__ = "current_decisions"
    __table_args__ = (
        CheckConstraint("rule_version = 'evidence-v1'", name="ck_current_decisions_rule"),
        CheckConstraint(
            "decision IN ('promote','retain','incomparable','correct')",
            name="ck_current_decisions_decision",
        ),
        CheckConstraint("execution_generation > 0", name="ck_current_decisions_generation"),
        UniqueConstraint(
            "candidate_run_id",
            "observed_current_run_id",
            "rule_version",
            name="uq_current_decisions_observation",
        ),
        Index("ix_current_decisions_occurrence_created", "occurrence_id", "created_at"),
    )

    candidate_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(ForeignKey("occurrences.id"), nullable=False)
    observed_current_run_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_runs.id"))
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    retry_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False)
    differences: Mapped[list[dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=False)
    current_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    candidate_evidence: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    audit_id: Mapped[str | None] = mapped_column(Text)
    audit_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    execution_attempt_id: Mapped[str] = mapped_column(
        ForeignKey("task_intents.attempt_id"), nullable=False
    )
    execution_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class ResultReview(Base):
    """Append-only review of existing results, separate from the first decision."""

    __tablename__ = "result_reviews"
    __table_args__ = (
        UniqueConstraint("occurrence_id", "idempotency_key", name="uq_result_reviews_request"),
        CheckConstraint("current_run_id <> candidate_run_id", name="ck_result_reviews_distinct"),
        CheckConstraint(
            "cause IN ('engine_upgrade','role_change','evidence_correction')",
            name="ck_result_reviews_cause",
        ),
        CheckConstraint(
            "decision IN ('promote','retain','incomparable','correct')",
            name="ck_result_reviews_decision",
        ),
        Index("ix_result_reviews_history", "occurrence_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(ForeignKey("occurrences.id"), nullable=False)
    current_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False)
    candidate_run_id: Mapped[str] = mapped_column(
        ForeignKey("current_decisions.candidate_run_id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    audit_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    audit_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    cause: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    current_evidence: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    candidate_evidence: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    differences: Mapped[list[dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


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

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    code_file: Mapped[str | None] = mapped_column(Text)
    code_id: Mapped[str] = mapped_column(Text, primary_key=True)
    debug_file: Mapped[str | None] = mapped_column(Text)
    debug_id: Mapped[str] = mapped_column(Text, primary_key=True)
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
        CheckConstraint("source = 'promotion'", name="ck_symbol_projection_states_source"),
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


class TaskIntent(Base):
    __tablename__ = "task_intents"
    __table_args__ = (
        UniqueConstraint("task_type", "logical_key", name="uq_task_intents_type_logical_key"),
        CheckConstraint(
            "schema_version IN ('1.0', '1.2')",
            name="ck_task_intents_schema_version",
        ),
        CheckConstraint(
            "task_type IN ('verify_upload', 'dispatch_workspace_role', 'analyze_frozen_run')",
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
            "task_type IN ('verify_upload', 'dispatch_workspace_role', 'analyze_frozen_run')",
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


def _default_wire_declared_length(context: Any) -> int:
    return int(context.get_current_parameters()["declared_length"])


class OccurrenceSubmission(Base):
    __tablename__ = "occurrence_submissions"
    __table_args__ = (
        Index("ix_occurrence_submissions_history", "occurrence_id", "upload_id"),
        CheckConstraint(
            "(occurrence_id IS NULL AND verified_at IS NULL) OR "
            "(occurrence_id IS NOT NULL AND verified_at IS NOT NULL)",
            name="ck_occurrence_submissions_verified",
        ),
    )

    upload_id: Mapped[str] = mapped_column(ForeignKey("uploads.id"), primary_key=True)
    occurrence_id: Mapped[str | None] = mapped_column(ForeignKey("occurrences.id"))
    label: Mapped[str | None] = mapped_column(Text)
    batch: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Upload(Base):
    __tablename__ = "uploads"
    __table_args__ = (
        UniqueConstraint("object_key", name="uq_uploads_object_key"),
        CheckConstraint("declared_length >= 0", name="ck_uploads_declared_length"),
        CheckConstraint(
            "verified_length IS NULL OR verified_length >= 0", name="ck_uploads_verified_length"
        ),
        CheckConstraint(
            "wire_encoding IN ('identity', 'zstd-v1')", name="ck_uploads_wire_encoding"
        ),
        CheckConstraint("wire_declared_length > 0", name="ck_uploads_wire_declared_length"),
        CheckConstraint(
            "verified_wire_length IS NULL OR verified_wire_length >= 0",
            name="ck_uploads_verified_wire_length",
        ),
        CheckConstraint(
            "wire_sha256_hint IS NULL OR wire_sha256_hint ~ '^[0-9a-f]{64}$'",
            name="ck_uploads_wire_sha256_hint",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "verified_wire_sha256 IS NULL OR verified_wire_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_uploads_verified_wire_sha256",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint("file_kind IN ('dmp', 'pe', 'pdb')", name="ck_uploads_file_kind"),
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
        CheckConstraint(
            "payload_deletion_attempts >= 0", name="ck_uploads_payload_deletion_attempts"
        ),
        Index(
            "ix_uploads_payload_gc_eligibility",
            "verification_status",
            "payload_deleted_at",
            "completed_at",
        ),
        Index(
            "ix_uploads_payload_gc_lease",
            "payload_delete_lease_expires_at",
            "id",
        ),
        Index(
            "ix_uploads_workspace_dmp_status_uploaded",
            "workspace_id",
            "file_kind",
            "verification_status",
            text("uploaded_at DESC"),
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"))
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    declared_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verified_length: Mapped[int | None] = mapped_column(BigInteger)
    client_sha256_hint: Mapped[str | None] = mapped_column(CHAR(64))
    verified_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    wire_encoding: Mapped[str] = mapped_column(
        Text, default="identity", server_default=text("'identity'")
    )
    wire_declared_length: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=_default_wire_declared_length
    )
    wire_sha256_hint: Mapped[str | None] = mapped_column(CHAR(64))
    verified_wire_length: Mapped[int | None] = mapped_column(BigInteger)
    verified_wire_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    source_ip: Mapped[str | None] = mapped_column(Text)
    file_kind: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, default="api", server_default=text("'api'")
    )
    verification_status: Mapped[str] = mapped_column(
        Text, default="INITIALIZED", server_default=text("'INITIALIZED'")
    )
    capture_profile: Mapped[str | None] = mapped_column(Text)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_deletion_reason: Mapped[str | None] = mapped_column(Text)
    payload_deletion_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    payload_delete_claim_token: Mapped[str | None] = mapped_column(Text)
    payload_delete_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    payload_delete_last_error: Mapped[str | None] = mapped_column(Text)


class ArtifactEntry(Base):
    """A user-visible binding of verified content to a Workspace or public scope."""

    __tablename__ = "artifact_entries"
    __table_args__ = (
        UniqueConstraint("upload_id", name="uq_artifact_entries_upload"),
        CheckConstraint("kind IN ('pe','pdb')", name="ck_artifact_entries_kind"),
        CheckConstraint("source IN ('api','cli','browser')", name="ck_artifact_entries_source"),
        CheckConstraint(
            "availability IN ('validating','waiting_for_pair','symbols_available',"
            "'identity_conflict','no_debug_identity','storage_unavailable')",
            name="ck_artifact_entries_availability",
        ),
        Index("ix_artifact_entries_scope_created", "workspace_id", text("created_at DESC")),
        Index("ix_artifact_entries_file_scope", "file_id", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    file_id: Mapped[str | None] = mapped_column(ForeignKey("catalog_files.id"))
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"))
    upload_id: Mapped[str] = mapped_column(ForeignKey("uploads.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="api")
    availability: Mapped[str] = mapped_column(Text, nullable=False, default="validating")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class OccurrenceVersionAudit(Base):
    __tablename__ = "occurrence_version_audits"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(ForeignKey("occurrences.id"), nullable=False)
    old_version: Mapped[str | None] = mapped_column(Text)
    new_version: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


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
