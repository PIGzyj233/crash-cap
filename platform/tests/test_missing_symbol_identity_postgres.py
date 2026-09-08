import os

import pytest
from alembic import command
from crashcap_api.models import MissingSymbol, MissingSymbolOccurrence
from crashcap_api.services.symbol_projection import replace_current_symbol_projection
from sqlalchemy import inspect, select, text

from .test_current_decisions_postgres import _seed_case
from .test_symbol_catalog_postgres import pg  # noqa: F401

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned PostgreSQL"
    ),
]


@pytest.mark.parametrize("pg", ["0002_user_auth"], indirect=True)
def test_upgrade_preserves_existing_missing_identity_rows(pg):  # noqa: F811
    engine, sessions, config = pg
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO workspaces(id,name) VALUES ('wsp_upgrade','upgrade')"))
        connection.execute(
            text("""INSERT INTO missing_symbols
            (id,workspace_id,identity_key,code_id,debug_id)
            VALUES ('msr_old','wsp_upgrade','ms_old','65F46B2D57AC000',
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1')""")
        )
    command.upgrade(config, "head")
    columns = {column["name"]: column for column in inspect(engine).get_columns("missing_symbols")}
    assert columns["debug_id"]["nullable"] and columns["code_id"]["nullable"]
    assert inspect(engine).get_pk_constraint("missing_symbols")["constrained_columns"] == ["id"]
    with sessions() as session:
        assert session.get(MissingSymbol, "msr_old").code_id == "65F46B2D57AC000"


def test_code_only_avcodec_and_debug_only_modules_persist_with_current_projection(pg):  # noqa: F811
    _, sessions, _ = pg
    with sessions.begin() as session:
        occurrence, run, _, _ = _seed_case(session)
        canonical = {
            "workspace_id": occurrence.workspace_id,
            "occurrence_id": occurrence.id,
            "analysis_id": run.id,
            "modules": [
                {
                    "code_file": (
                        r"D:\CloudGameBundle\apps\lightstreamer\current\bin\avcodec-61.dll"
                    ),
                    "code_id": "65F46B2D57AC000",
                    "debug_file": None,
                    "debug_id": None,
                    "status": "missing_pdb",
                },
                {
                    "code_file": "debug-only.dll",
                    "code_id": None,
                    "debug_file": "debug-only.pdb",
                    "debug_id": "a" * 32 + "1",
                    "status": "missing_pe",
                },
                {
                    "code_file": "unknown.dll",
                    "code_id": None,
                    "debug_file": None,
                    "debug_id": None,
                    "status": "missing_pe",
                },
            ],
        }
        for _ in range(2):
            result = replace_current_symbol_projection(
                session, occurrence=occurrence, run=run, canonical=canonical, source="promotion"
            )
            assert result.missing_count == 3
        workspace_id, occurrence_id = occurrence.workspace_id, occurrence.id
    with sessions() as session:
        rows = list(
            session.scalars(select(MissingSymbol).where(MissingSymbol.workspace_id == workspace_id))
        )
        assert len(rows) == 3 and all(row.affected_occurrence_count == 1 for row in rows)
        avcodec = next(row for row in rows if row.code_file.endswith("avcodec-61.dll"))
        assert avcodec.debug_id is None and avcodec.debug_file is None
        assert avcodec.code_id == "65F46B2D57AC000"
        assert (
            len(
                list(
                    session.scalars(
                        select(MissingSymbolOccurrence).where(
                            MissingSymbolOccurrence.occurrence_id == occurrence_id
                        )
                    )
                )
            )
            == 3
        )
