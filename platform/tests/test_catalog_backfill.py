from __future__ import annotations

import hashlib
import os

import pytest
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import (
    Artifact,
    ArtifactBlob,
    ArtifactBlobPair,
    Build,
    BuildModule,
    CatalogFileLocation,
    CatalogPair,
    CatalogPairOrigin,
    SymbolCatalogBackfill,
    Workspace,
    utcnow,
)
from crashcap_api.services.artifact_payloads import ArtifactBlobCodec, configure_zstd_payload
from crashcap_api.services.catalog_backfill import backfill_catalog
from crashcap_api.storage import create_object_store
from crashcap_worker.core_runner import CoreExecutor
from sqlalchemy import func, select

from .test_symbol_imports import CORE, FIXTURE, PAIR

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("QAI_HISTORY_REAL"),
        reason="requires explicit real Core history qualification",
    ),
]


@pytest.fixture
def history(tmp_path):
    settings = Settings.for_test(tmp_path).model_copy(
        update={
            "core_executor": "local",
            "core_command": str(CORE),
            "symbol_imports_enabled": True,
            "task_handoff_mode": "outbox",
            "task_receipt_mode": "strict",
        }
    )
    settings = Settings.model_validate(settings.model_dump())
    database = Database(settings)
    yield database.sessions, create_object_store(settings), CoreExecutor(settings), tmp_path
    database.dispose()


def seed(history, suffix="one", *, compressed=False, publication=False, bad_pdb=False):
    sessions, store, _, temporary = history
    files = {
        "pe": (FIXTURE / "null_read_target.exe").read_bytes(),
        "pdb": b"not a PDB" if bad_pdb else (FIXTURE / "null_read_target.pdb").read_bytes(),
    }
    with sessions.begin() as session:
        workspace = Workspace(id="ws_" + suffix, name="history-" + suffix, display_name="History")
        session.add(workspace)
        session.flush()
        build = Build(id="bld_" + suffix, workspace_id=workspace.id, version="same-human-version")
        session.add(build)
        session.flush()
        module = BuildModule(
            id="mod_" + suffix,
            build_id=build.id,
            code_file="same.exe",
            debug_file="same.pdb",
            role="dependency",
        )
        session.add(module)
        session.flush()
        blobs = {}
        for kind, content in files.items():
            sha = hashlib.sha256(content).hexdigest()
            object_key = f"history/{suffix}/{kind}"
            blob = None
            if compressed or publication:
                blob = ArtifactBlob(
                    id=f"abl_{suffix}_{kind}",
                    workspace_id=workspace.id,
                    kind=kind,
                    sha256=sha,
                    size=len(content),
                    object_key=object_key,
                    payload_object_key=object_key,
                    payload_size=len(content),
                    payload_sha256=sha,
                    verification_status="verified",
                    verified_at=utcnow(),
                    payload_verified_at=utcnow(),
                )
                if compressed:
                    raw, encoded = (
                        temporary / f"{suffix}.{kind}",
                        temporary / f"{suffix}.{kind}.zst",
                    )
                    raw.write_bytes(content)
                    payload = ArtifactBlobCodec().encode_file(
                        raw, encoded, kind=kind, encoding="zstd-v1"
                    )
                    object_key += ".zst"
                    configure_zstd_payload(
                        blob, object_key=object_key, payload=payload, verified_at=utcnow()
                    )
                    store.put_file(object_key, encoded, "application/zstd")
                else:
                    store.put_bytes(object_key, content, "application/octet-stream")
                session.add(blob)
                session.flush()
                blobs[kind] = blob.id
            else:
                store.put_bytes(object_key, content, "application/octet-stream")
            session.add(
                Artifact(
                    id=f"art_{suffix}_{kind}",
                    build_id=build.id,
                    module_id=module.id,
                    kind=kind,
                    logical_name="filename-is-not-identity." + kind,
                    sha256=sha,
                    size=len(content),
                    object_key=object_key,
                    artifact_blob_id=blob.id if blob else None,
                    verification_status="verified",
                )
            )
        session.flush()
        if publication:
            session.add(
                ArtifactBlobPair(
                    id="abp_" + suffix,
                    workspace_id=workspace.id,
                    pe_blob_id=blobs["pe"],
                    pdb_blob_id=blobs["pdb"],
                    state="published",
                    published_at=utcnow(),
                )
            )
    return files


def scan(history, *, apply=False, limit=1, retry_gaps=False):
    sessions, store, core, _ = history
    reports, cursor = [], None
    for _ in range(100):
        report = backfill_catalog(
            sessions, store, core, after=cursor, limit=limit, apply=apply, retry_gaps=retry_gaps
        )
        reports.append(report)
        if not report["has_more"]:
            return reports
        cursor = report["next_cursor"]
    pytest.fail("bounded test inventory did not drain")


def old_rows(sessions):
    with sessions() as session:
        return {
            model.__tablename__: [
                tuple(getattr(row, column.name) for column in model.__table__.columns)
                for row in session.scalars(select(model).order_by(model.id))
            ]
            for model in (Build, BuildModule, Artifact, ArtifactBlob, ArtifactBlobPair)
        }


def test_real_raw_zstd_publication_dry_run_restart_and_no_historical_rewrite(history):
    sessions, store, _, _ = history
    seed(history)
    seed(history, "compressed", compressed=True, publication=True)
    before = old_rows(sessions)
    before_objects = sorted((obj.key, obj.size) for obj in store.iter_objects("history"))
    dry = scan(history)
    cases = [case for page in dry for case in page["cases"]]
    assert len(cases) == 3 and all(case["outcome"] == "would_admit" for case in cases), cases
    assert all(case["pair_id"] == PAIR for case in cases)
    assert list(store.iter_objects("catalog")) == []
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SymbolCatalogBackfill)) == 0
    applied = scan(history, apply=True)
    assert all(case["outcome"] == "admitted" for page in applied for case in page["cases"])
    objects = sorted((obj.key, obj.size) for obj in store.iter_objects("catalog"))
    replay = scan(history, apply=True, limit=2)
    assert all(case["outcome"] == "already_admitted" for page in replay for case in page["cases"])
    assert objects == sorted((obj.key, obj.size) for obj in store.iter_objects("catalog"))
    assert old_rows(sessions) == before
    assert before_objects == sorted((obj.key, obj.size) for obj in store.iter_objects("history"))
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(CatalogPair)) == 1
        assert session.scalar(select(func.count()).select_from(CatalogPairOrigin)) == 3
        assert all(row.attempt_count == 1 for row in session.scalars(select(SymbolCatalogBackfill)))
        assert all(
            row.retention_basis == "platform_owned"
            for row in session.scalars(select(CatalogFileLocation))
        )


def test_all_same_module_combinations_keep_different_valid_content(history):
    sessions, store, _, _ = history
    files = seed(history)
    alternate = files["pe"] + b"valid PE overlay with different retained content"
    store.put_bytes("history/alternate", alternate, "application/octet-stream")
    with sessions.begin() as session:
        session.add(
            Artifact(
                id="art_one_pe_newer",
                build_id="bld_one",
                module_id="mod_one",
                kind="pe",
                logical_name="same.exe",
                sha256=hashlib.sha256(alternate).hexdigest(),
                size=len(alternate),
                object_key="history/alternate",
                verification_status="verified",
            )
        )
    reports = scan(history, apply=True)
    cases = [case for page in reports for case in page["cases"]]
    assert len(cases) == 2 and all(case["outcome"] == "admitted" for case in cases), cases
    assert len({case["pair_id"] for case in cases}) == 2
    with sessions() as session:
        pairs = session.scalars(select(CatalogPair)).all()
        assert len(pairs) == 2
        assert len({pair.code_id for pair in pairs}) == len({pair.debug_id for pair in pairs}) == 1


def test_missing_and_invalid_history_are_isolated_and_gaps_retry(history):
    sessions, store, _, _ = history
    files = seed(history, "missing")
    seed(history, "bad", bad_pdb=True)
    seed(history, "good")
    store.delete("history/missing/pdb")
    reports = scan(history, apply=True)
    cases = [case for page in reports for case in page["cases"]]
    assert sorted(case["outcome"] for case in cases) == ["admitted", "rejected", "retryable"], cases
    assert {case["reason"] for case in cases if case["reason"]} == {
        "ARTIFACT_IDENTIFY_FAILED",
        "HISTORICAL_OBJECT_MISSING",
    }
    store.put_bytes("history/missing/pdb", files["pdb"], "application/octet-stream")
    retried = scan(history, apply=True, retry_gaps=True)
    assert sorted(case["outcome"] for page in retried for case in page["cases"]) == [
        "admitted",
        "rejected",
    ]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(CatalogPair)) == 1
        assert session.scalar(select(func.count()).select_from(CatalogPairOrigin)) == 2


def test_cutoff_and_opaque_cursor_do_not_silently_absorb_late_arrivals(history):
    sessions, store, core, _ = history
    seed(history, "one")
    seed(history, "two")
    first = backfill_catalog(sessions, store, core, limit=1)
    seed(history, "000late")
    second = backfill_catalog(sessions, store, core, limit=1, after=first["next_cursor"])
    assert not second["has_more"]
    assert all("000late" not in part for row in second["cases"] for part in row["locator"])
    assert sum(page["scanned"] for page in scan(history)) == 3
    for cursor in ("not a cursor", first["next_cursor"]):
        with pytest.raises(ValueError, match="cursor"):
            backfill_catalog(sessions, store, core, after=cursor, retry_gaps=True)


def test_source_change_during_io_rejects_stale_admission(history, monkeypatch):
    from crashcap_api.services import catalog_backfill

    sessions, _, _, _ = history
    seed(history)
    prepare = catalog_backfill.prepare_catalog_pair

    def changed(*args):
        result = prepare(*args)
        with sessions.begin() as session:
            session.get(Artifact, "art_one_pe").code_id = "123456789"
        return result

    monkeypatch.setattr(catalog_backfill, "prepare_catalog_pair", changed)
    reports = scan(history, apply=True)
    assert reports[0]["cases"][0]["reason"] == "HISTORICAL_SOURCE_CHANGED"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(CatalogPair)) == 0
        assert session.scalars(select(SymbolCatalogBackfill)).one().outcome == "retryable"


@pytest.mark.parametrize(
    "code_id,reason",
    [
        ("123456789", "HISTORICAL_MODULE_IDENTITY_MISMATCH"),
        ("1234", "HISTORICAL_MODULE_IDENTITY_INVALID"),
    ],
)
def test_blob_payload_hash_and_recorded_module_identity_are_checked(history, code_id, reason):
    sessions, store, _, _ = history
    seed(history, "compressed", compressed=True)
    seed(history, "identity")
    with sessions.begin() as session:
        blob = session.get(ArtifactBlob, "abl_compressed_pdb")
        store.put_bytes(blob.payload_object_key, b"x" * blob.payload_size, "application/zstd")
        session.get(Artifact, "art_identity_pe").code_id = code_id
    cases = [case for page in scan(history, apply=True) for case in page["cases"]]
    assert {case["reason"] for case in cases} == {
        "payload_sha256_mismatch",
        reason,
    }
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(CatalogPair)) == 0


def test_incomplete_unverified_and_unscoped_files_are_not_silently_skipped(history):
    sessions, _, _, _ = history
    seed(history)
    with sessions.begin() as session:
        session.get(Artifact, "art_one_pdb").module_id = None
        session.get(Artifact, "art_one_pe").verification_status = "pending"
    cases = [case for page in scan(history, apply=True) for case in page["cases"]]
    assert len(cases) == 2
    assert {case["reason"] for case in cases} == {
        "HISTORICAL_PAIR_INCOMPLETE",
        "HISTORICAL_ARTIFACT_NOT_VERIFIED",
    }
