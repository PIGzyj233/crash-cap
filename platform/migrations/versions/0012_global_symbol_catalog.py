"""Add the global content catalog; no historical admission or payload movement."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_global_symbol_catalog"
down_revision: str | None = "0011_canonical_dual_reader"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen DDL, deliberately independent of future application ORM revisions.
DDL = (
    """CREATE TABLE catalog_watermark (
        id INTEGER PRIMARY KEY, revision BIGINT NOT NULL,
        CONSTRAINT ck_catalog_watermark CHECK (id = 1 AND revision >= 0))""",
    """CREATE TABLE catalog_files (
        id CHAR(64) PRIMARY KEY, kind TEXT NOT NULL, raw_sha256 CHAR(64) NOT NULL,
        raw_size BIGINT NOT NULL, code_id TEXT, debug_id TEXT NOT NULL,
        architecture TEXT NOT NULL, validator_version TEXT NOT NULL,
        verification_object_key TEXT NOT NULL, verification_sha256 CHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_catalog_files_content UNIQUE (kind, raw_sha256),
        CONSTRAINT ck_catalog_files_shape CHECK (kind IN ('pe','pdb') AND raw_size > 0),
        CONSTRAINT ck_catalog_files_arch CHECK (architecture IN ('x86_64','unknown')),
        CONSTRAINT ck_catalog_files_pe_identity CHECK (kind <> 'pe' OR code_id IS NOT NULL))""",
    """CREATE TABLE catalog_file_locations (
        id CHAR(64) PRIMARY KEY, file_id CHAR(64) NOT NULL REFERENCES catalog_files(id),
        object_key TEXT NOT NULL, payload_encoding TEXT NOT NULL,
        payload_sha256 CHAR(64) NOT NULL, payload_size BIGINT NOT NULL,
        retention_basis TEXT NOT NULL, artifact_blob_id TEXT REFERENCES artifact_blobs(id),
        state TEXT NOT NULL, verification_object_key TEXT NOT NULL,
        verification_sha256 CHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_catalog_locations_object UNIQUE (object_key),
        CONSTRAINT ck_catalog_locations_payload CHECK (payload_encoding IN ('identity','zstd-v1') AND payload_size > 0),
        CONSTRAINT ck_catalog_locations_state CHECK (state IN ('available','unavailable')),
        CONSTRAINT ck_catalog_locations_retention CHECK (retention_basis IN ('platform_owned','canonical_blob')),
        CONSTRAINT ck_catalog_locations_blob_binding CHECK ((retention_basis = 'canonical_blob') = (artifact_blob_id IS NOT NULL)))""",
    """CREATE TABLE catalog_pairs (
        id CHAR(64) PRIMARY KEY, pe_file_id CHAR(64) NOT NULL REFERENCES catalog_files(id),
        pdb_file_id CHAR(64) NOT NULL REFERENCES catalog_files(id),
        code_id TEXT NOT NULL, debug_id TEXT NOT NULL, architecture TEXT NOT NULL,
        state TEXT NOT NULL, qualification_version BIGINT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_catalog_pairs_content UNIQUE (pe_file_id, pdb_file_id),
        CONSTRAINT ck_catalog_pairs_qualification CHECK (state IN ('active','withdrawn') AND qualification_version > 0),
        CONSTRAINT ck_catalog_pairs_arch CHECK (architecture = 'x86_64'))""",
    """CREATE TABLE catalog_pair_origins (
        id TEXT PRIMARY KEY, pair_id CHAR(64) NOT NULL REFERENCES catalog_pairs(id),
        origin_type TEXT NOT NULL, origin_key TEXT NOT NULL,
        source_workspace_id TEXT REFERENCES workspaces(id), build_id TEXT REFERENCES builds(id),
        details JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_catalog_origins_source_pair UNIQUE (origin_type, origin_key, pair_id),
        CONSTRAINT ck_catalog_origins_type CHECK (origin_type IN ('import_item','build_artifacts','publication')))""",
    """CREATE TABLE catalog_identity_memberships (
        pair_id CHAR(64) PRIMARY KEY REFERENCES catalog_pairs(id),
        code_id TEXT NOT NULL, debug_id TEXT NOT NULL, architecture TEXT NOT NULL)""",
    """CREATE TABLE catalog_pair_reviews (
        id TEXT PRIMARY KEY, pair_id CHAR(64) NOT NULL REFERENCES catalog_pairs(id),
        qualification_version BIGINT NOT NULL, state TEXT NOT NULL,
        idempotency_key TEXT NOT NULL, request_sha256 CHAR(64) NOT NULL,
        reason TEXT NOT NULL, evidence_object_key TEXT NOT NULL, evidence_sha256 CHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_catalog_reviews_version UNIQUE (pair_id, qualification_version),
        CONSTRAINT uq_catalog_reviews_idempotency UNIQUE (idempotency_key),
        CONSTRAINT ck_catalog_reviews_state CHECK (state IN ('active','withdrawn') AND qualification_version > 1))""",
    """CREATE TABLE catalog_changes (
        revision BIGINT PRIMARY KEY, pair_id CHAR(64) NOT NULL REFERENCES catalog_pairs(id),
        code_id TEXT NOT NULL, debug_id TEXT NOT NULL, architecture TEXT NOT NULL,
        change_type TEXT NOT NULL, affects_selection BOOLEAN NOT NULL,
        review_id TEXT REFERENCES catalog_pair_reviews(id), details JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT ck_catalog_changes_revision CHECK (revision > 0))""",
    "CREATE INDEX ix_catalog_locations_file ON catalog_file_locations (file_id, state)",
    "CREATE INDEX ix_catalog_memberships_code ON catalog_identity_memberships (code_id, architecture)",
    "CREATE INDEX ix_catalog_memberships_debug ON catalog_identity_memberships (debug_id, architecture)",
    "INSERT INTO catalog_watermark (id, revision) VALUES (1, 0)",
)


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)


def downgrade() -> None:
    tables = ("catalog_changes", "catalog_pair_reviews", "catalog_pair_origins",
              "catalog_identity_memberships", "catalog_pairs", "catalog_file_locations", "catalog_files")
    for table in tables:
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise RuntimeError("Retained catalog evidence exists; keep the compatible catalog schema")
    for table in (*tables, "catalog_watermark"):
        op.execute(f"DROP TABLE {table}")
