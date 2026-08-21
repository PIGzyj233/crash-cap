"""Create the Phase 1 Crash-Cap PostgreSQL schema.

This revision intentionally contains only the anonymous, trusted-intranet
Phase 1 data model.  It does not create users, roles, tenants, or membership
tables.  PostgreSQL 15 or newer is required for the null-safe unique
constraint on ``missing_symbols``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_phase1_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TIMESTAMPTZ = sa.DateTime(timezone=True)
JSONB = postgresql.JSONB

UPLOAD_STATUSES = (
    "INITIALIZED",
    "UPLOADING",
    "UPLOADED",
    "VERIFYING",
    "ACCEPTED",
    "QUARANTINED",
    "REJECTED",
)
ANALYSIS_STATUSES = (
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
)


def _in_check(column: str, values: Sequence[str]) -> str:
    """Build a readable SQL CHECK expression for a finite text state set."""

    quoted = ", ".join("'%s'" % value for value in values)
    return "%s IN (%s)" % (column, quoted)


def upgrade() -> None:
    """Create every Phase 1 table, constraint, and documented index."""

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=False, server_default=sa.text("'windows'")),
        sa.Column(
            "default_architecture",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'x86_64'"),
        ),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default=sa.text("180")),
        sa.Column(
            "symbol_inventory_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id", name="pk_workspaces"),
        sa.UniqueConstraint("name", name="uq_workspaces_name"),
        sa.CheckConstraint("platform = 'windows'", name="ck_workspaces_platform"),
        sa.CheckConstraint("default_architecture = 'x86_64'", name="ck_workspaces_architecture"),
        sa.CheckConstraint("retention_days > 0", name="ck_workspaces_retention_days"),
        sa.CheckConstraint("symbol_inventory_version >= 0", name="ck_workspaces_symbol_inventory"),
    )

    op.create_table(
        "builds",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("build_number", sa.Text(), nullable=True),
        sa.Column("commit_sha", sa.Text(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("architecture", sa.Text(), nullable=False, server_default=sa.text("'x86_64'")),
        sa.Column("toolchain", sa.Text(), nullable=True),
        sa.Column("manifest_object_key", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id", name="pk_builds"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_builds_workspace_id",
        ),
        sa.CheckConstraint("architecture = 'x86_64'", name="ck_builds_architecture"),
    )
    op.create_index(
        "ix_builds_workspace_created_at",
        "builds",
        ["workspace_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "build_modules",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("build_id", sa.Text(), nullable=False),
        sa.Column("code_file", sa.Text(), nullable=False),
        sa.Column("debug_file", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("code_id", sa.Text(), nullable=True),
        sa.Column("debug_id", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id", name="pk_build_modules"),
        sa.ForeignKeyConstraint(
            ["build_id"],
            ["builds.id"],
            name="fk_build_modules_build_id",
        ),
        sa.CheckConstraint(
            "role IN ('entrypoint', 'owned', 'dependency')",
            name="ck_build_modules_role",
        ),
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("build_id", sa.Text(), nullable=False),
        sa.Column("module_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("logical_name", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("code_id", sa.Text(), nullable=True),
        sa.Column("debug_id", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id", name="pk_artifacts"),
        sa.ForeignKeyConstraint(
            ["build_id"],
            ["builds.id"],
            name="fk_artifacts_build_id",
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["build_modules.id"],
            name="fk_artifacts_module_id",
        ),
        sa.CheckConstraint(
            "kind IN ('pe', 'pdb', 'source_bundle')",
            name="ck_artifacts_kind",
        ),
        sa.CheckConstraint(
            "verification_status IN ('pending', 'verified', 'rejected_fastlink', 'pdb_mismatch', 'pe_mismatch', 'corrupted', 'rejected_format')",
            name="ck_artifacts_verification_status",
        ),
        sa.CheckConstraint("size >= 0", name="ck_artifacts_size"),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_artifacts_sha256",
        ),
    )
    op.create_index("ix_artifacts_debug_id", "artifacts", ["debug_id"])
    op.create_index("ix_artifacts_code_id", "artifacts", ["code_id"])
    op.create_index("ix_artifacts_sha256", "artifacts", ["sha256"])

    op.create_table(
        "dump_blobs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("dump_kind", sa.Text(), nullable=False, server_default=sa.text("'user_minidump'")),
        sa.Column("architecture", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.Text(), nullable=False, server_default=sa.text("'VERIFYING'")),
        sa.Column("uploaded_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", TIMESTAMPTZ, nullable=True),
        sa.Column("deleted_at", TIMESTAMPTZ, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dump_blobs"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_dump_blobs_workspace_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "sha256",
            name="uq_dump_blobs_workspace_sha256",
        ),
        sa.CheckConstraint("size >= 0", name="ck_dump_blobs_size"),
        sa.CheckConstraint("dump_kind = 'user_minidump'", name="ck_dump_blobs_kind"),
        sa.CheckConstraint(
            _in_check("verification_status", UPLOAD_STATUSES),
            name="ck_dump_blobs_verification_status",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_dump_blobs_sha256",
        ),
    )

    # current_run_id is added after analysis_runs because analysis_runs also
    # points back to occurrences.  This keeps the revision valid on a fresh
    # PostgreSQL database without weakening either foreign key.
    op.create_table(
        "occurrences",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("dump_blob_id", sa.Text(), nullable=False),
        sa.Column("reported_build_id", sa.Text(), nullable=True),
        sa.Column("current_run_id", sa.Text(), nullable=True),
        sa.Column("dump_timestamp", TIMESTAMPTZ, nullable=True),
        sa.Column("reported_at", TIMESTAMPTZ, nullable=True),
        sa.Column("uploaded_at", TIMESTAMPTZ, nullable=False),
        sa.Column("occurred_at", TIMESTAMPTZ, nullable=False),
        sa.Column("time_source", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id", name="pk_occurrences"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_occurrences_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["dump_blob_id"],
            ["dump_blobs.id"],
            name="fk_occurrences_dump_blob_id",
        ),
        sa.ForeignKeyConstraint(
            ["reported_build_id"],
            ["builds.id"],
            name="fk_occurrences_reported_build_id",
        ),
        sa.UniqueConstraint("dump_blob_id", name="uq_occurrences_dump_blob_id"),
        sa.CheckConstraint(
            "time_source IN ('dump', 'reported', 'uploaded', 'manual')",
            name="ck_occurrences_time_source",
        ),
    )

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("occurrence_id", sa.Text(), nullable=False),
        sa.Column("run_spec", JSONB(), nullable=False),
        sa.Column("reported_build_id", sa.Text(), nullable=True),
        sa.Column("resolved_build_id", sa.Text(), nullable=True),
        sa.Column("resolution_method", sa.Text(), nullable=False),
        sa.Column("resolution_evidence", JSONB(), nullable=True),
        sa.Column("core_version", sa.Text(), nullable=False),
        sa.Column("core_image_digest", sa.Text(), nullable=False),
        sa.Column("symbolicator_version", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False, server_default=sa.text("'1.0'")),
        sa.Column("grouping_version", sa.Text(), nullable=False, server_default=sa.text("'group-v1.0'")),
        sa.Column("normalization_version", sa.Text(), nullable=False, server_default=sa.text("'norm-v1.0'")),
        sa.Column("symbol_inventory_version", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.CHAR(length=64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("quality_score", sa.REAL(), nullable=True),
        sa.Column("result_object_key", sa.Text(), nullable=True),
        sa.Column("raw_object_prefix", sa.Text(), nullable=True),
        sa.Column("started_at", TIMESTAMPTZ, nullable=True),
        sa.Column("finished_at", TIMESTAMPTZ, nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_runs"),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["occurrences.id"],
            name="fk_analysis_runs_occurrence_id",
        ),
        sa.ForeignKeyConstraint(
            ["reported_build_id"],
            ["builds.id"],
            name="fk_analysis_runs_reported_build_id",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_build_id"],
            ["builds.id"],
            name="fk_analysis_runs_resolved_build_id",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_analysis_runs_idempotency_key"),
        sa.CheckConstraint(
            _in_check("resolution_method", ("reported", "auto_unique", "manual", "ambiguous", "unresolved")),
            name="ck_analysis_runs_resolution_method",
        ),
        sa.CheckConstraint(
            _in_check("status", ANALYSIS_STATUSES),
            name="ck_analysis_runs_status",
        ),
        sa.CheckConstraint("schema_version = '1.0'", name="ck_analysis_runs_schema_version"),
        sa.CheckConstraint("grouping_version = 'group-v1.0'", name="ck_analysis_runs_grouping_version"),
        sa.CheckConstraint("normalization_version = 'norm-v1.0'", name="ck_analysis_runs_normalization_version"),
        sa.CheckConstraint("symbol_inventory_version >= 0", name="ck_analysis_runs_symbol_inventory"),
        sa.CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0.0 AND quality_score <= 1.0)",
            name="ck_analysis_runs_quality_score",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[0-9a-fA-F]{64}$'",
            name="ck_analysis_runs_idempotency_key",
        ),
    )
    op.create_foreign_key(
        "fk_occurrences_current_run_id",
        "occurrences",
        "analysis_runs",
        ["current_run_id"],
        ["id"],
    )

    op.create_table(
        "analysis_summaries",
        sa.Column("analysis_run_id", sa.Text(), nullable=False),
        sa.Column("occurrence_id", sa.Text(), nullable=False),
        sa.Column("resolved_build_id", sa.Text(), nullable=True),
        sa.Column("version", sa.Text(), nullable=True),
        sa.Column("exception_code", sa.Text(), nullable=True),
        sa.Column("exception_name", sa.Text(), nullable=True),
        sa.Column("access_type", sa.Text(), nullable=True),
        sa.Column("crash_address", sa.Text(), nullable=True),
        sa.Column("crashing_thread_id", sa.BigInteger(), nullable=True),
        sa.Column("fault_module", sa.Text(), nullable=True),
        sa.Column("top_function", sa.Text(), nullable=True),
        sa.Column("top_source_file", sa.Text(), nullable=True),
        sa.Column("top_source_line", sa.Integer(), nullable=True),
        sa.Column("symbol_coverage", sa.REAL(), nullable=True),
        sa.Column("unwind_reliability", sa.REAL(), nullable=True),
        sa.Column("artifact_completeness", sa.REAL(), nullable=True),
        sa.Column("exact_fingerprint", sa.Text(), nullable=True),
        sa.Column("family_fingerprint", sa.Text(), nullable=True),
        sa.Column("crashing_frames", JSONB(), nullable=True),
        sa.Column("crash_type", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("analysis_run_id", name="pk_analysis_summaries"),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name="fk_analysis_summaries_analysis_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["occurrences.id"],
            name="fk_analysis_summaries_occurrence_id",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_build_id"],
            ["builds.id"],
            name="fk_analysis_summaries_resolved_build_id",
        ),
        sa.CheckConstraint(
            "crash_type IN ('crash', 'hang', 'unknown')",
            name="ck_analysis_summaries_crash_type",
        ),
        sa.CheckConstraint(
            "symbol_coverage IS NULL OR (symbol_coverage >= 0.0 AND symbol_coverage <= 1.0)",
            name="ck_analysis_summaries_symbol_coverage",
        ),
        sa.CheckConstraint(
            "unwind_reliability IS NULL OR (unwind_reliability >= 0.0 AND unwind_reliability <= 1.0)",
            name="ck_analysis_summaries_unwind_reliability",
        ),
        sa.CheckConstraint(
            "artifact_completeness IS NULL OR (artifact_completeness >= 0.0 AND artifact_completeness <= 1.0)",
            name="ck_analysis_summaries_artifact_completeness",
        ),
    )
    op.create_index(
        "ix_analysis_summaries_exact_fingerprint",
        "analysis_summaries",
        ["exact_fingerprint"],
    )
    op.create_index(
        "ix_analysis_summaries_exception_fault_module",
        "analysis_summaries",
        ["exception_code", "fault_module"],
    )

    op.create_table(
        "crash_groups",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("group_type", sa.Text(), nullable=False, server_default=sa.text("'exact'")),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("representative_run_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("first_seen", TIMESTAMPTZ, nullable=False),
        sa.Column("last_seen", TIMESTAMPTZ, nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("first_build_id", sa.Text(), nullable=True),
        sa.Column("last_build_id", sa.Text(), nullable=True),
        sa.Column("owner", sa.Text(), nullable=True),
        sa.Column("issue_url", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_crash_groups"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_crash_groups_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["representative_run_id"],
            ["analysis_runs.id"],
            name="fk_crash_groups_representative_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["first_build_id"],
            ["builds.id"],
            name="fk_crash_groups_first_build_id",
        ),
        sa.ForeignKeyConstraint(
            ["last_build_id"],
            ["builds.id"],
            name="fk_crash_groups_last_build_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "group_type",
            "fingerprint",
            name="uq_crash_groups_workspace_type_fingerprint",
        ),
        sa.CheckConstraint("group_type = 'exact'", name="ck_crash_groups_type"),
        sa.CheckConstraint(
            "status IN ('open', 'investigating', 'fixed', 'ignored')",
            name="ck_crash_groups_status",
        ),
        sa.CheckConstraint("occurrence_count >= 0", name="ck_crash_groups_occurrence_count"),
    )

    op.create_table(
        "group_memberships",
        sa.Column("occurrence_id", sa.Text(), nullable=False),
        sa.Column("group_id", sa.Text(), nullable=False),
        sa.Column("analysis_run_id", sa.Text(), nullable=False),
        sa.Column("similarity", sa.REAL(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("grouping_evidence_json", JSONB(), nullable=False),
        sa.Column("assigned_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("occurrence_id", name="pk_group_memberships"),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["occurrences.id"],
            name="fk_group_memberships_occurrence_id",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["crash_groups.id"],
            name="fk_group_memberships_group_id",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name="fk_group_memberships_analysis_run_id",
        ),
        sa.CheckConstraint("similarity = 1.0", name="ck_group_memberships_similarity"),
    )

    # The design describes this append-only table in §10.10 and §9.4 even
    # though it does not repeat a separate column table.  Keeping both sides
    # of a move makes the current-membership projection reconstructible.
    op.create_table(
        "group_membership_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("occurrence_id", sa.Text(), nullable=False),
        sa.Column("previous_group_id", sa.Text(), nullable=True),
        sa.Column("group_id", sa.Text(), nullable=True),
        sa.Column("analysis_run_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("similarity", sa.REAL(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("grouping_evidence_json", JSONB(), nullable=False),
        sa.Column("recorded_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id", name="pk_group_membership_history"),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["occurrences.id"],
            name="fk_group_membership_history_occurrence_id",
        ),
        sa.ForeignKeyConstraint(
            ["previous_group_id"],
            ["crash_groups.id"],
            name="fk_group_membership_history_previous_group_id",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["crash_groups.id"],
            name="fk_group_membership_history_group_id",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name="fk_group_membership_history_analysis_run_id",
        ),
        sa.CheckConstraint(
            "action IN ('assign', 'move', 'unclassify')",
            name="ck_group_membership_history_action",
        ),
        sa.CheckConstraint("similarity = 1.0", name="ck_group_membership_history_similarity"),
    )
    op.create_index(
        "ix_group_membership_history_occurrence_recorded",
        "group_membership_history",
        ["occurrence_id", "recorded_at"],
    )

    op.create_table(
        "missing_symbols",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("code_file", sa.Text(), nullable=True),
        sa.Column("code_id", sa.Text(), nullable=True),
        sa.Column("debug_file", sa.Text(), nullable=True),
        sa.Column("debug_id", sa.Text(), nullable=True),
        sa.Column("first_seen", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_seen", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("affected_occurrence_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_missing_symbols_workspace_id",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'ignored')",
            name="ck_missing_symbols_status",
        ),
        sa.CheckConstraint(
            "affected_occurrence_count >= 0",
            name="ck_missing_symbols_affected_count",
        ),
    )
    # PostgreSQL 15+ syntax is required here.  A normal UNIQUE constraint
    # treats NULL debug/code IDs as distinct and would permit duplicate rows.
    op.execute(
        sa.text(
            "ALTER TABLE missing_symbols "
            "ADD CONSTRAINT uq_missing_symbols_workspace_debug_code "
            "UNIQUE NULLS NOT DISTINCT (workspace_id, debug_id, code_id)"
        )
    )

    op.create_table(
        "uploads",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("build_id", sa.Text(), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("declared_length", sa.BigInteger(), nullable=False),
        sa.Column("verified_length", sa.BigInteger(), nullable=True),
        sa.Column("client_sha256_hint", sa.CHAR(length=64), nullable=True),
        sa.Column("verified_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("uploaded_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("source_ip", sa.Text(), nullable=True),
        sa.Column("file_kind", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.Text(), nullable=False, server_default=sa.text("'INITIALIZED'")),
        sa.Column("capture_profile", sa.Text(), nullable=True),
        sa.Column("reported_build_id", sa.Text(), nullable=True),
        sa.Column("reported_at", TIMESTAMPTZ, nullable=True),
        sa.Column("expires_at", TIMESTAMPTZ, nullable=True),
        sa.Column("completed_at", TIMESTAMPTZ, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_uploads"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_uploads_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["build_id"],
            ["builds.id"],
            name="fk_uploads_build_id",
        ),
        sa.ForeignKeyConstraint(
            ["reported_build_id"],
            ["builds.id"],
            name="fk_uploads_reported_build_id",
        ),
        sa.UniqueConstraint("object_key", name="uq_uploads_object_key"),
        sa.CheckConstraint("declared_length >= 0", name="ck_uploads_declared_length"),
        sa.CheckConstraint(
            "verified_length IS NULL OR verified_length >= 0",
            name="ck_uploads_verified_length",
        ),
        sa.CheckConstraint(
            "file_kind IN ('dmp', 'pe', 'pdb', 'source_bundle')",
            name="ck_uploads_file_kind",
        ),
        sa.CheckConstraint(
            _in_check("verification_status", UPLOAD_STATUSES),
            name="ck_uploads_verification_status",
        ),
        sa.CheckConstraint(
            "client_sha256_hint IS NULL OR client_sha256_hint ~ '^[0-9a-fA-F]{64}$'",
            name="ck_uploads_client_sha256_hint",
        ),
        sa.CheckConstraint(
            "verified_sha256 IS NULL OR verified_sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_uploads_verified_sha256",
        ),
    )

    op.create_table(
        "operation_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False, server_default=sa.text("'anonymous'")),
        sa.Column("occurred_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("source_ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_operation_logs"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_operation_logs_workspace_id",
        ),
        sa.CheckConstraint("actor = 'anonymous'", name="ck_operation_logs_actor"),
    )


def downgrade() -> None:
    """Drop the Phase 1 schema in dependency order."""

    op.drop_table("operation_logs")
    op.drop_table("uploads")
    op.drop_constraint(
        "uq_missing_symbols_workspace_debug_code",
        "missing_symbols",
        type_="unique",
    )
    op.drop_table("missing_symbols")
    op.drop_index(
        "ix_group_membership_history_occurrence_recorded",
        table_name="group_membership_history",
    )
    op.drop_table("group_membership_history")
    op.drop_table("group_memberships")
    op.drop_table("crash_groups")
    op.drop_index(
        "ix_analysis_summaries_exception_fault_module",
        table_name="analysis_summaries",
    )
    op.drop_index(
        "ix_analysis_summaries_exact_fingerprint",
        table_name="analysis_summaries",
    )
    op.drop_table("analysis_summaries")
    op.drop_constraint("fk_occurrences_current_run_id", "occurrences", type_="foreignkey")
    op.drop_table("analysis_runs")
    op.drop_table("occurrences")
    op.drop_table("dump_blobs")
    op.drop_index("ix_artifacts_sha256", table_name="artifacts")
    op.drop_index("ix_artifacts_code_id", table_name="artifacts")
    op.drop_index("ix_artifacts_debug_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_table("build_modules")
    op.drop_index("ix_builds_workspace_created_at", table_name="builds")
    op.drop_table("builds")
    op.drop_table("workspaces")
