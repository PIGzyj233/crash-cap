"""Durable inspect references, demands, immutable targets and catalog fanout cursor."""

from alembic import op
from sqlalchemy import text

revision = "0015_analysis_demands"
down_revision = "0014_catalog_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE dump_inspections (
        id CHAR(64) PRIMARY KEY, dump_blob_id TEXT NOT NULL REFERENCES dump_blobs(id),
        inspector_version TEXT NOT NULL, inspector_provenance TEXT NOT NULL,
        dump_sha256 CHAR(64) NOT NULL, dump_size BIGINT NOT NULL,
        object_key TEXT NOT NULL, object_sha256 CHAR(64) NOT NULL, modules JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_dump_inspections_version
            UNIQUE(dump_blob_id, inspector_version, inspector_provenance),
        CONSTRAINT ck_dump_inspections_size CHECK(dump_size > 0)
    )""")
    op.execute("""CREATE TABLE auto_analysis_demands (
        id TEXT PRIMARY KEY, occurrence_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
        inspection_id CHAR(64) REFERENCES dump_inspections(id), state TEXT NOT NULL,
        reason TEXT NOT NULL, generation BIGINT NOT NULL, retry_attempt INTEGER NOT NULL,
        change_sequence BIGINT NOT NULL, planned_sequence BIGINT NOT NULL,
        index_revision BIGINT NOT NULL, first_event_at TIMESTAMPTZ, last_event_at TIMESTAMPTZ,
        not_before TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_analysis_demands_occurrence UNIQUE(occurrence_id),
        FOREIGN KEY (occurrence_id, workspace_id) REFERENCES occurrences(id, workspace_id),
        CONSTRAINT ck_analysis_demands_counters CHECK(generation >= 0 AND retry_attempt >= 0),
        CONSTRAINT ck_analysis_demands_sequence
            CHECK(planned_sequence >= 0 AND change_sequence >= planned_sequence),
        CONSTRAINT ck_analysis_demands_revision CHECK(index_revision >= 0),
        CONSTRAINT ck_analysis_demands_state CHECK(state IN (
            'preparing','coalescing','queued','running','updated','retained','needs_review',
            'retry_wait','retry_exhausted','cannot_recompute','paused'))
    )""")
    op.create_index(
        "ix_analysis_demands_ready",
        "auto_analysis_demands",
        ["state", "not_before", "workspace_id", "id"],
    )
    op.execute("""CREATE TABLE dump_symbol_references (
        occurrence_id TEXT NOT NULL REFERENCES occurrences(id), module_index INTEGER NOT NULL,
        inspection_id CHAR(64) NOT NULL REFERENCES dump_inspections(id),
        code_id TEXT, debug_id TEXT, architecture TEXT NOT NULL,
        PRIMARY KEY(occurrence_id, module_index),
        CONSTRAINT ck_dump_symbol_references_index CHECK(module_index >= 0)
    )""")
    op.create_index(
        "ix_dump_symbol_references_code", "dump_symbol_references", ["code_id", "occurrence_id"]
    )
    op.create_index(
        "ix_dump_symbol_references_debug", "dump_symbol_references", ["debug_id", "occurrence_id"]
    )
    op.execute("""CREATE TABLE analysis_demand_targets (
        demand_id TEXT NOT NULL REFERENCES auto_analysis_demands(id), generation BIGINT NOT NULL,
        inspection_id CHAR(64) NOT NULL REFERENCES dump_inspections(id),
        resolution_fingerprint CHAR(64) NOT NULL, context_sha256 CHAR(64) NOT NULL,
        cause TEXT NOT NULL,
        manifest_object_key TEXT NOT NULL, manifest_sha256 CHAR(64) NOT NULL,
        catalog_revision BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(demand_id, generation),
        CONSTRAINT ck_demand_targets_counters CHECK(generation > 0 AND catalog_revision >= 0),
        CONSTRAINT ck_demand_targets_cause CHECK(cause IN (
            'initial','symbol_refresh','role_change','engine_upgrade','evidence_correction','manual'))
    )""")
    op.execute("""CREATE TABLE analysis_event_cursors (
        id TEXT PRIMARY KEY, revision BIGINT NOT NULL, after_occurrence_id TEXT,
        CONSTRAINT ck_analysis_event_cursors_revision CHECK(revision >= 0)
    )""")


def downgrade() -> None:
    tables = (
        "analysis_demand_targets",
        "dump_symbol_references",
        "auto_analysis_demands",
        "dump_inspections",
        "analysis_event_cursors",
    )
    for table in tables:
        query = text(f"SELECT EXISTS(SELECT 1 FROM {table})")  # noqa: S608 - fixed table allowlist
        if op.get_bind().execute(query).scalar_one():
            raise RuntimeError("Retained analysis demand evidence requires the compatible schema")
    for table in tables:
        op.drop_table(table)
