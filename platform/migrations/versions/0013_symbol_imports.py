"""Independent symbol import staging and durable verification attempts.

This is schema-only. No old Build, Blob, Run, or catalog record is rewritten.
"""

from alembic import op
from sqlalchemy import text

revision = "0013_symbol_imports"
down_revision = "0012_global_symbol_catalog"
branch_labels = None
depends_on = None

OLD_TYPES = "'verify_upload','ingest_artifact','publish_artifact_blob_pair','reindex_symbols','analyze_occurrence'"


def _task_constraints(new: bool) -> None:
    versions = "'1.0','1.1','1.2'" if new else "'1.0','1.1'"
    types = OLD_TYPES + ", 'verify_symbol_import_pair'" if new else OLD_TYPES
    for table, name, expression in (
        ("task_intents", "ck_task_intents_schema_version", f"schema_version IN ({versions})"),
        ("task_intents", "ck_task_intents_type", f"task_type IN ({types})"),
        ("task_executions", "ck_task_executions_type", f"task_type IN ({types})"),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, expression)


def upgrade() -> None:
    _task_constraints(True)
    op.execute("""CREATE TABLE symbol_imports (
        id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
        request_sha256 CHAR(64) NOT NULL, source_label TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )""")
    op.execute("""CREATE TABLE symbol_import_items (
        id TEXT PRIMARY KEY, import_id TEXT NOT NULL REFERENCES symbol_imports(id),
        client_pair_id TEXT NOT NULL, position INTEGER NOT NULL, state TEXT NOT NULL,
        attempt_count INTEGER NOT NULL, pair_id CHAR(64) REFERENCES catalog_pairs(id),
        error_code TEXT,
        CONSTRAINT uq_symbol_import_item_client UNIQUE(import_id, client_pair_id),
        CONSTRAINT uq_symbol_import_item_position UNIQUE(import_id, position),
        CONSTRAINT ck_symbol_import_item_state CHECK (
            state IN ('staging','queued','verifying','available','rejected','retry_exhausted')),
        CONSTRAINT ck_symbol_import_item_counts CHECK(attempt_count >= 0 AND position >= 0),
        CONSTRAINT ck_symbol_import_item_pair CHECK(state <> 'available' OR pair_id IS NOT NULL)
    )""")
    op.execute("""CREATE TABLE symbol_import_files (
        id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES symbol_import_items(id),
        kind TEXT NOT NULL, name TEXT NOT NULL, raw_sha256 CHAR(64) NOT NULL,
        raw_size BIGINT NOT NULL, object_key TEXT UNIQUE,
        CONSTRAINT uq_symbol_import_file_kind UNIQUE(item_id, kind),
        CONSTRAINT ck_symbol_import_file_shape CHECK(kind IN ('pe','pdb') AND raw_size > 0)
    )""")
    op.execute("""CREATE TABLE symbol_import_attempts (
        id TEXT PRIMARY KEY REFERENCES task_intents(attempt_id),
        item_id TEXT NOT NULL REFERENCES symbol_import_items(id), ordinal INTEGER NOT NULL,
        state TEXT NOT NULL, error_code TEXT, created_at TIMESTAMPTZ NOT NULL,
        started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
        CONSTRAINT uq_symbol_import_attempt_ordinal UNIQUE(item_id, ordinal),
        CONSTRAINT ck_symbol_import_attempt_ordinal CHECK(ordinal > 0),
        CONSTRAINT ck_symbol_import_attempt_state CHECK(
            state IN ('queued','running','succeeded','rejected','failed','exhausted'))
    )""")
    op.create_index(
        "ix_symbol_import_attempt_state", "symbol_import_attempts", ["state", "created_at"]
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        text(
            "SELECT EXISTS(SELECT 1 FROM symbol_imports) OR EXISTS("
            "SELECT 1 FROM task_intents WHERE schema_version = '1.2') OR EXISTS("
            "SELECT 1 FROM task_executions WHERE task_type = 'verify_symbol_import_pair')"
        )
    ).scalar_one():
        raise RuntimeError(
            "Retained symbol import records require the compatible schema; disable writes instead"
        )
    for table in (
        "symbol_import_attempts",
        "symbol_import_files",
        "symbol_import_items",
        "symbol_imports",
    ):
        op.drop_table(table)
    _task_constraints(False)
