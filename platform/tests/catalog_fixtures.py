"""Fixture builders for scheduler/review tests; production accepts single files only."""

from dataclasses import dataclass

from crashcap_api.frozen_inputs import digest
from crashcap_api.models import CatalogPair, Upload
from crashcap_api.services.artifact_catalog import accept_file
from crashcap_api.services.symbol_catalog import FileEvidence, LocationEvidence
from crashcap_worker.catalog_validation import catalog_validator_version
from crashcap_worker.file_ingest import prepare_file


@dataclass(frozen=True)
class OriginEvidence:
    origin_type: str
    origin_key: str
    source_workspace_id: str | None
    unused: str | None
    details: dict


def origin(key="item-one"):
    return OriginEvidence("upload", key, None, None, {})


def pair_evidence(pe_sha="a" * 64, pdb_sha="b" * 64, code="123456789"):
    pe = FileEvidence(
        "pe", pe_sha, 17, code, "2" * 32 + "1", "x86_64", "unit-fixture", "proof/files", "f" * 64
    )
    pdb = FileEvidence(
        "pdb", pdb_sha, 17, None, pe.debug_id, "unknown", "unit-fixture", "proof/files", "f" * 64
    )
    locations = {
        f.kind: (
            LocationEvidence(
                f"catalog/files/{f.id}/raw",
                "identity",
                f.raw_sha256,
                f.raw_size,
                "platform_owned",
                "proof/payload",
                "f" * 64,
            ),
        )
        for f in (pe, pdb)
    }
    return pe, pdb, locations


def admit_pair(session, pe, pdb, locations, origin):
    """Convenience fixture: perform two separate admissions in one test transaction."""
    for evidence in (pe, pdb):
        uid = "upl_" + digest([origin.origin_key, evidence.kind])[:26]
        upload = session.get(Upload, uid)
        if upload is None:
            upload = Upload(
                id=uid,
                workspace_id=origin.source_workspace_id,
                original_filename="fixture." + evidence.kind,
                object_key="staging/" + uid,
                declared_length=evidence.raw_size,
                file_kind=evidence.kind,
                verification_status="ACCEPTED",
                source="api",
            )
            session.add(upload)
            session.flush()
        accept_file(session, upload, evidence, locations[evidence.kind][0])
    session.flush()
    return session.get(CatalogPair, digest(["pair-v1", pe.raw_sha256, pdb.raw_sha256]))


@dataclass(frozen=True)
class PreparedPair:
    pe: FileEvidence
    pdb: FileEvidence
    locations: dict


def prepare_catalog_pair(core, store, pe, pdb, *, payload_encoding="identity"):
    catalog_validator_version(core)
    if payload_encoding != "identity":
        raise ValueError("Uploads retain original validated bytes")
    prepared = []
    for path, kind in ((pe, "pe"), (pdb, "pdb")):
        import hashlib

        with path.open("rb") as source:
            sha = hashlib.file_digest(source, "sha256").hexdigest()
        prepared.append(prepare_file(core, store, path, kind, sha, path.stat().st_size))
    return PreparedPair(
        prepared[0][0], prepared[1][0], {"pe": (prepared[0][1],), "pdb": (prepared[1][1],)}
    )
