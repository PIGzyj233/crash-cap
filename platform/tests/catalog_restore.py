"""Restore only runner-owned metadata and payload into a separate environment."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from crashcap_api.models import Base
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DOCKER = shutil.which("docker")


def docker(*args: str) -> str:
    assert DOCKER is not None
    return subprocess.run(  # noqa: S603 - runner-owned Docker resources
        [DOCKER, *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,  # noqa: S607
    ).stdout.strip()


def payload_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def metadata_rows(engine):
    with engine.connect() as connection:
        return {
            table.name: sorted((tuple(row) for row in connection.execute(table.select())), key=repr)
            for table in Base.metadata.tables.values()
        }


def qualify_restore(live):
    token = os.environ["QAI_MATERIAL_RUN_TOKEN"]
    sources = docker("ps", "-q", "--filter", f"label=crashcap.qai.catalog={token}").splitlines()
    assert len(sources) == 1, "Restore qualification requires exactly one runner-owned database"
    source = sources[0]
    source_url = make_url(live["settings"].database_url)
    assert source_url.host == "127.0.0.1"
    assert docker("port", source, "5432/tcp") == f"127.0.0.1:{source_url.port}"
    source_engine = create_engine(source_url)
    with source_engine.connect() as connection:
        schema = connection.execute(text("select current_schema()")).scalar_one()
    assert schema.startswith("qai_catalog_") and schema.removeprefix("qai_catalog_").isalnum()
    output = live["output"] / "restore"
    output.mkdir()
    dump_path = output / "metadata.dump"
    original_payload = live["settings"].object_store_local_root
    backup_payload = original_payload.parent.with_name("qai-restore-backup") / original_payload.name
    restored_payload = original_payload.parent.with_name("qai-restore-data") / original_payload.name
    restored = None
    restored_engine = None
    restore_token = uuid.uuid4().hex
    receipt = {"status": "RUNNING", "application_database_touched": False}
    try:
        before = metadata_rows(source_engine)
        with dump_path.open("wb") as stream:
            assert DOCKER is not None
            subprocess.run(  # noqa: S603 - only the label-verified test container
                [
                    DOCKER,
                    "exec",
                    source,
                    "pg_dump",
                    "-U",
                    "postgres",  # noqa: S607
                    "-d",
                    source_url.database,
                    "--schema",
                    schema,
                    "--format=custom",
                ],
                stdout=stream,
                stderr=subprocess.PIPE,
                check=True,
                timeout=60,
            )
        shutil.copytree(original_payload, backup_payload)
        hashes = payload_hashes(original_payload)
        assert hashes and hashes == payload_hashes(backup_payload)
        image = docker("inspect", "--format", "{{.Image}}", source)
        restored = docker(
            "run",
            "--pull=never",
            "-d",
            "--name",
            "qai-restore-" + restore_token,
            "--label",
            "crashcap.qai.restore=" + restore_token,
            "-e",
            "POSTGRES_PASSWORD=qai-local-fixture",
            "-e",
            "POSTGRES_DB=restored",
            "-p",
            "127.0.0.1::5432",
            image,
        )
        for _ in range(60):
            try:
                docker("exec", restored, "pg_isready", "-U", "postgres", "-d", "restored")
                break
            except subprocess.CalledProcessError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Restored PostgreSQL did not become ready")
        docker("cp", str(dump_path), restored + ":/metadata.dump")
        docker(
            "exec",
            restored,
            "pg_restore",
            "-U",
            "postgres",
            "-d",
            "restored",
            "--exit-on-error",
            "--no-owner",
            "/metadata.dump",
        )
        mapping = docker("port", restored, "5432/tcp")
        assert mapping.startswith("127.0.0.1:")
        restored_url = source_url.set(port=int(mapping.split(":")[1]), database="restored")
        restored_engine = create_engine(restored_url)
        shutil.copytree(backup_payload, restored_payload)
        assert before == metadata_rows(restored_engine)
        assert hashes == payload_hashes(restored_payload)
        assert before == metadata_rows(source_engine), "Backup changed source metadata"
        assert hashes == payload_hashes(original_payload), "Backup changed source payload"
        receipt.update(
            status="METADATA_PAYLOAD_PASS",
            cold_cache_replay="NOT_RUN",
            metadata_sha256=hashlib.sha256(dump_path.read_bytes()).hexdigest(),
            table_counts={name: len(rows) for name, rows in before.items()},
            payload_sha256=hashes,
            source_container=source,
            restored_container=restored,
            postgres_image=image,
            backup_payload=str(backup_payload),
            restored_payload=str(restored_payload),
        )
        from .restored_replay import replay_restored

        replay_restored(
            live["settings"].model_copy(
                update={
                    "database_url": restored_url.render_as_string(hide_password=False),
                    "object_store_local_root": restored_payload,
                }
            ),
            live,
            receipt,
        )
        assert before == metadata_rows(restored_engine)
        assert hashes == payload_hashes(restored_payload)
        receipt["status"] = "PASS"
    except Exception as error:
        receipt.update(status="FAIL", error_type=type(error).__name__)
        raise
    finally:
        if restored_engine is not None:
            restored_engine.dispose()
        source_engine.dispose()
        if restored is not None:
            assert (
                docker(
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "crashcap.qai.restore"}}',
                    restored,
                )
                == restore_token
            )
            docker("rm", "-f", "-v", restored)
            receipt["restored_container_and_volume_removed"] = True
        (output / "result.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
