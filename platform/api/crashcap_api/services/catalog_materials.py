"""Read one immutable catalog content identity through verified physical replicas."""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from ..frozen_inputs import digest
from ..models import CatalogFile, CatalogFileLocation, CatalogPair
from ..storage import ObjectNotFoundError, ObjectStore
from .artifact_payloads import (
    MAX_RAW_BYTES,
    STREAM_CHUNK_SIZE,
    TEMP_DISK_RESERVE_BYTES,
    ArtifactBlobCodec,
    ArtifactPayloadError,
)


class CatalogMaterialError(RuntimeError):
    def __init__(self, code: str, failure_class: str, *, status: int | None = None) -> None:
        super().__init__(code)
        self.code, self.failure_class = code, failure_class
        # Symbolicator retains HTTP status in its candidate diagnostics but drops
        # the response body. Never label permanent/unknown material failures 503.
        self.status = (
            status
            if status is not None
            else {
                "transient": 503,
                "permanent": 422,
                "unknown": 500,
            }[failure_class]
        )


@dataclass(frozen=True)
class Location:
    id: str
    object_key: str
    encoding: str
    payload_sha256: str
    payload_size: int


@dataclass(frozen=True)
class CatalogMaterial:
    pair_id: str
    file_id: str
    kind: str
    raw_sha256: str
    raw_size: int
    locations: tuple[Location, ...]
    has_more_locations: bool


def _require(condition: bool) -> None:
    if not condition:
        raise CatalogMaterialError("CATALOG_IDENTITY_INVALID", "permanent")


def select_material(
    session: Session,
    pair_id: str,
    debug_id: str,
    kind: str,
    *,
    max_locations: int,
    only_available: bool = False,
    workspace_id: str | None = None,
) -> CatalogMaterial:
    if not 1 <= max_locations <= 200 or kind not in {"pe", "pdb"}:
        raise ValueError("Invalid catalog material selector")
    pair = session.get(CatalogPair, pair_id)
    if pair is None:
        raise CatalogMaterialError("CATALOG_PAIR_NOT_FOUND", "permanent", status=404)
    from .artifact_catalog import pair_is_visible

    if not pair_is_visible(session, pair_id, workspace_id):
        raise CatalogMaterialError("CATALOG_PAIR_NOT_FOUND", "permanent", status=404)
    pe, pdb = session.get(CatalogFile, pair.pe_file_id), session.get(CatalogFile, pair.pdb_file_id)
    _require(pe is not None and pdb is not None)
    assert pe is not None and pdb is not None
    for file, expected_kind in ((pe, "pe"), (pdb, "pdb")):
        _require(
            file.kind == expected_kind
            and re.fullmatch(r"[0-9a-f]{64}", file.raw_sha256) is not None
        )
        _require(file.id == digest(["catalog-file-v1", expected_kind, file.raw_sha256]))
        _require(0 < file.raw_size <= MAX_RAW_BYTES[expected_kind])
    _require(pair.id == digest(["pair-v1", pe.raw_sha256, pdb.raw_sha256]))
    _require(
        pair.debug_id == pe.debug_id == pdb.debug_id
        and pair.code_id == pe.code_id
        and pair.architecture == pe.architecture == "x86_64"
    )
    if pair.debug_id != debug_id:
        # No alternate identity/name lookup is permitted on a pair endpoint.
        raise CatalogMaterialError("CATALOG_PATH_NOT_FOUND", "permanent", status=404)
    file = pe if kind == "pe" else pdb
    rows = session.scalars(
        select(CatalogFileLocation)
        .where(CatalogFileLocation.file_id == file.id)
        .where(CatalogFileLocation.state == "available" if only_available else true())
        .order_by(CatalogFileLocation.state, CatalogFileLocation.id)
        .limit(max_locations + 1)
    ).all()
    # A previously marked unavailable replica may be readable again. Verify its
    # exact content for a frozen reader; this does not restore catalog qualification.
    return CatalogMaterial(
        pair.id,
        file.id,
        kind,
        file.raw_sha256,
        file.raw_size,
        tuple(
            Location(
                row.id, row.object_key, row.payload_encoding, row.payload_sha256, row.payload_size
            )
            for row in rows[:max_locations]
        ),
        len(rows) > max_locations,
    )


def _materialize_location(
    store: ObjectStore, material: CatalogMaterial, location: Location, destination: Path
) -> None:
    if location.encoding not in {"identity", "zstd-v1"}:
        raise CatalogMaterialError("CATALOG_ENCODING_INVALID", "permanent")
    encoding: Literal["identity", "zstd-v1"] = (
        "identity" if location.encoding == "identity" else "zstd-v1"
    )
    limit = MAX_RAW_BYTES[material.kind] + (STREAM_CHUNK_SIZE if encoding == "zstd-v1" else 0)
    if (
        not 0 < location.payload_size <= limit
        or re.fullmatch(r"[0-9a-f]{64}", location.payload_sha256) is None
    ):
        raise CatalogMaterialError("CATALOG_PAYLOAD_METADATA_INVALID", "permanent")
    if encoding == "identity" and (location.payload_sha256, location.payload_size) != (
        material.raw_sha256,
        material.raw_size,
    ):
        raise CatalogMaterialError("CATALOG_PAYLOAD_METADATA_INVALID", "permanent")
    payload = destination.parent / "payload"
    if (
        shutil.disk_usage(destination.parent).free
        < location.payload_size + material.raw_size + TEMP_DISK_RESERVE_BYTES
    ):
        raise CatalogMaterialError("CATALOG_TEMP_CAPACITY_INSUFFICIENT", "transient")
    sha, size = hashlib.sha256(), 0
    try:
        with payload.open("xb") as output:
            for block in store.stream(location.object_key, STREAM_CHUNK_SIZE):
                size += len(block)
                if size > location.payload_size:
                    raise CatalogMaterialError("CATALOG_PAYLOAD_SIZE_MISMATCH", "permanent")
                sha.update(block)
                output.write(block)
        if size != location.payload_size or sha.hexdigest() != location.payload_sha256:
            raise CatalogMaterialError("CATALOG_PAYLOAD_HASH_MISMATCH", "permanent")
        ArtifactBlobCodec().decode_file(
            payload,
            destination,
            kind=material.kind,
            encoding=encoding,
            expected_raw_size=material.raw_size,
            expected_raw_sha256=material.raw_sha256,
        )
    finally:
        payload.unlink(missing_ok=True)


def materialize_catalog_file(
    store: ObjectStore, material: CatalogMaterial, destination: Path
) -> Location:
    if destination.exists():
        raise ValueError("Catalog material destination must be new")
    failures: list[CatalogMaterialError] = []
    for location in material.locations:
        try:
            _materialize_location(store, material, location, destination)
            return location
        except CatalogMaterialError as error:
            failures.append(error)
        except ArtifactPayloadError as error:
            transient = error.code.startswith("temp_capacity")
            failures.append(
                CatalogMaterialError(
                    "CATALOG_" + error.code.upper(), "transient" if transient else "permanent"
                )
            )
        except ObjectNotFoundError:
            failures.append(CatalogMaterialError("CATALOG_OBJECT_MISSING", "transient"))
        except OSError:
            failures.append(CatalogMaterialError("CATALOG_IO_FAILED", "transient"))
        except Exception:
            # A transport/driver error is not proof of permanent missing content.
            failures.append(CatalogMaterialError("CATALOG_READ_FAILED", "unknown"))
    if material.has_more_locations:
        raise CatalogMaterialError("CATALOG_LOCATION_BUDGET_EXHAUSTED", "unknown")
    if not failures:
        raise CatalogMaterialError("CATALOG_NO_RETAINED_LOCATION", "unknown")
    if len({(failure.code, failure.failure_class) for failure in failures}) == 1:
        raise failures[0]
    classes = {failure.failure_class for failure in failures}
    raise CatalogMaterialError(
        "CATALOG_REPLICAS_UNAVAILABLE", next(iter(classes)) if len(classes) == 1 else "unknown"
    )
