"""Real binary acceptance boundaries and fenced retry after a temporary failure."""

import struct

import pytest
from crashcap_api.models import ArtifactEntry, CatalogFile, TaskExecution, TaskIntent, Upload
from sqlalchemy import select

from .test_upload_v3 import PDB, PE, space, upload
from .test_upload_v3 import v3 as upload_fixture

v3 = upload_fixture


def test_valid_pe_without_debug_identity_is_retained(v3):
    app, client = v3
    data = bytearray(PE.read_bytes())
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    optional = pe + 24
    assert struct.unpack_from("<H", data, optional)[0] == 0x20B
    struct.pack_into("<II", data, optional + 112 + 6 * 8, 0, 0)
    result = upload(v3, PE, space(client, "no-debug"), payload=bytes(data))
    assert result["status"] == "ACCEPTED" and result["availability"] == "no_debug_identity"
    with app.state.database.sessions() as session:
        file = session.scalar(select(CatalogFile))
        assert file.debug_id is None and file.code_id


def test_unsupported_machine_is_not_mislabeled_x64(v3):
    _app, client = v3
    data = bytearray(PE.read_bytes())
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    struct.pack_into("<H", data, pe + 4, 0x14C)
    assert upload(v3, PE, space(client, "unsupported"), payload=bytes(data))["status"] == "REJECTED"


def fastlink_marker_fixture():
    """Put the documented S_FASTLINK symbol marker into a real PDB's symbol stream."""
    data = bytearray(PDB.read_bytes())
    block_size = struct.unpack_from("<I", data, 32)[0]
    directory_size = struct.unpack_from("<I", data, 44)[0]
    block_map = struct.unpack_from("<I", data, 52)[0]
    blocks = struct.unpack_from(
        "<" + "I" * ((directory_size + block_size - 1) // block_size), data, block_map * block_size
    )
    directory = b"".join(data[b * block_size : (b + 1) * block_size] for b in blocks)[
        :directory_size
    ]
    count = struct.unpack_from("<I", directory)[0]
    sizes = struct.unpack_from("<" + "I" * count, directory, 4)
    cursor = 4 + 4 * count
    streams = []
    for size in sizes:
        n = 0 if size == 0xFFFFFFFF else (size + block_size - 1) // block_size
        streams.append(struct.unpack_from("<" + "I" * n, directory, cursor))
        cursor += 4 * n
    dbi = b"".join(data[b * block_size : (b + 1) * block_size] for b in streams[3])
    symbol_stream = struct.unpack_from("<H", dbi, 20)[0]
    start = streams[symbol_stream][0] * block_size
    assert struct.unpack_from("<H", data, start)[0] >= 2
    struct.pack_into("<H", data, start + 2, 0x1167)
    return bytes(data)


def test_fastlink_marker_is_rejected_by_the_real_parser(v3, tmp_path):
    app, client = v3
    payload = fastlink_marker_fixture()
    path = tmp_path / "fastlink.pdb"
    path.write_bytes(payload)
    assert app.state.processor.core.identify_artifact(path, "pdb")["is_fastlink"] is True
    assert upload(v3, PDB, space(client, "fastlink"), payload=payload)["status"] == "REJECTED"
    with app.state.database.sessions() as session:
        assert session.scalar(select(ArtifactEntry)) is None


def test_temporary_worker_error_retries_same_upload_without_polluting_success(v3, monkeypatch):
    import crashcap_worker.file_ingest as worker

    app, client = v3
    workspace = space(client, "retry")
    first = upload(v3, PE, workspace)
    original = worker.prepare_file

    def fail(*_args, **_kwargs):
        raise OSError("temporary parser process failure")

    monkeypatch.setattr(worker, "prepare_file", fail)
    with pytest.raises(OSError, match="temporary"):
        upload(v3, PDB, workspace)
    with app.state.database.sessions() as session:
        pending = session.scalar(select(Upload).where(Upload.file_kind == "pdb"))
        uid = pending.id
        assert pending.verification_status == "VERIFYING"
        message = dict(
            session.scalar(select(TaskIntent).where(TaskIntent.logical_key == uid)).message
        )
    monkeypatch.setattr(worker, "prepare_file", original)
    app.state.processor.verify_upload(message)
    assert client.get(f"/api/v3/uploads/{uid}").json()["availability"] == "symbols_available"
    assert client.get(f"/api/v3/uploads/{first['upload_id']}").json()["status"] == "ACCEPTED"
    with app.state.database.sessions() as session:
        execution = session.scalar(select(TaskExecution).where(TaskExecution.logical_key == uid))
        assert execution.generation == 2 and execution.outcome == "succeeded"
