"""Append-only exact-identity Workspace module role declarations."""

from alembic import op
from sqlalchemy import text

revision = "0016_workspace_module_roles"
down_revision = "0015_analysis_demands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_task_intents_type", "task_intents", type_="check")
    op.create_check_constraint(
        "ck_task_intents_type",
        "task_intents",
        "task_type IN ('verify_upload','ingest_artifact','publish_artifact_blob_pair',"
        "'reindex_symbols','analyze_occurrence','verify_symbol_import_pair',"
        "'dispatch_workspace_role')",
    )
    op.drop_constraint("ck_task_executions_type", "task_executions", type_="check")
    op.create_check_constraint(
        "ck_task_executions_type",
        "task_executions",
        "task_type IN ('verify_upload','ingest_artifact','publish_artifact_blob_pair',"
        "'reindex_symbols','analyze_occurrence','verify_symbol_import_pair',"
        "'dispatch_workspace_role')",
    )
    op.execute(
        """ALTER TABLE workspaces ADD COLUMN module_role_version BIGINT NOT NULL DEFAULT 0,
        ADD CONSTRAINT ck_workspaces_module_role_version CHECK(module_role_version >= 0)"""
    )
    op.execute("""CREATE TABLE workspace_module_roles (
        workspace_id TEXT NOT NULL REFERENCES workspaces(id), version BIGINT NOT NULL,
        code_id TEXT NOT NULL, debug_id TEXT NOT NULL, architecture TEXT NOT NULL,
        role TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(workspace_id, version),
        CONSTRAINT ck_workspace_module_roles_version CHECK(version > 0),
        CONSTRAINT ck_workspace_module_roles_architecture CHECK(architecture = 'x86_64'),
        CONSTRAINT ck_workspace_module_roles_role CHECK(role IN ('owned','dependency')),
        CONSTRAINT ck_workspace_module_roles_code_id CHECK(code_id ~ '^[0-9a-f]{9,24}$'),
        CONSTRAINT ck_workspace_module_roles_debug_id CHECK(debug_id ~ '^[0-9a-f]{33,40}$')
    )""")
    op.execute("""CREATE INDEX ix_workspace_module_roles_identity_version
        ON workspace_module_roles(workspace_id, code_id, debug_id, architecture, version DESC)""")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM task_intents WHERE task_type = "
                "'dispatch_workspace_role') OR EXISTS(SELECT 1 FROM task_executions "
                "WHERE task_type = 'dispatch_workspace_role')"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Retained Workspace role fanout tasks require the compatible schema")
    if (
        op.get_bind()
        .execute(text("SELECT EXISTS(SELECT 1 FROM workspace_module_roles)"))
        .scalar_one()
    ):
        raise RuntimeError("Retained Workspace role declarations require the compatible schema")
    op.drop_table("workspace_module_roles")
    op.drop_constraint("ck_workspaces_module_role_version", "workspaces", type_="check")
    op.drop_column("workspaces", "module_role_version")
    op.drop_constraint("ck_task_executions_type", "task_executions", type_="check")
    op.create_check_constraint(
        "ck_task_executions_type",
        "task_executions",
        "task_type IN ('verify_upload','ingest_artifact','publish_artifact_blob_pair',"
        "'reindex_symbols','analyze_occurrence','verify_symbol_import_pair')",
    )
    op.drop_constraint("ck_task_intents_type", "task_intents", type_="check")
    op.create_check_constraint(
        "ck_task_intents_type",
        "task_intents",
        "task_type IN ('verify_upload','ingest_artifact','publish_artifact_blob_pair',"
        "'reindex_symbols','analyze_occurrence','verify_symbol_import_pair')",
    )
