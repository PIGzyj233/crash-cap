from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from crashcap_api.config import Settings
from crashcap_api.frozen_inputs import canonical_bytes
from crashcap_worker.core_runner import CoreExecutionError, DockerVolumeWorkspace
from crashcap_worker.frozen_core import FrozenAssignment, FrozenCoreExecutor
from pydantic import ValidationError

from .test_frozen_inputs import DUMP_BYTES, inputs


def config(root, **updates):
    values = Settings.for_test(root).model_dump()
    values.update(
        core_executor="local",
        frozen_core_enabled=True,
        frozen_symbolicator_url="http://127.0.0.1:3029",
        frozen_pair_source_root="http://127.0.0.1:3030",
        core_image_digest="sha256:" + "e" * 64,
        frozen_symbolicator_image_digest="sha256:" + "f" * 64,
    )
    values.update(updates)
    return Settings(**values)


def staged(root):
    root.mkdir()
    run, manifest, inspect = inputs()
    encoded = canonical_bytes(run)
    (root / "run.json").write_bytes(encoded)
    (root / "resolution-manifest.json").write_bytes(canonical_bytes(manifest))
    (root / "inspect.json").write_bytes(canonical_bytes(inspect))
    (root / "dump.dmp").write_bytes(DUMP_BYTES)
    pe, pdb = root / "pair.pe", root / "pair.pdb"
    pe.write_bytes(b"actual verification belongs to Core")
    pdb.write_bytes(b"actual verification belongs to Core")
    return FrozenAssignment(
        run["run_id"],
        run["occurrence_id"],
        run["context"]["workspace_id"],
        hashlib.sha256(encoded).hexdigest(),
    ), {"a" * 64: (pe, pdb)}


def test_frozen_worker_default_off_before_any_io(tmp_path):
    executor = FrozenCoreExecutor(Settings.for_test(tmp_path))
    with pytest.raises(CoreExecutionError) as caught:
        executor.execute(
            tmp_path / "absent",
            FrozenAssignment("r", "o", "w", "0" * 64),
            {},
            raw_object_prefix="runs/r/attempts/1",
        )
    assert caught.value.code == "FROZEN_WRITER_DISABLED"
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize(
    "updates",
    [
        {"core_executor": "fake"},
        {"frozen_symbolicator_url": None},
        {"frozen_pair_source_root": "http://user:password@host/"},
        {"frozen_symbolicator_url": "http://symbolicator-gateway:3021"},
        {"frozen_symbolicator_image_digest": None},
        {"frozen_symbolicator_image_digest": "bad"},
        {"frozen_allow_local_core_sentinel": True, "environment": "production"},
        {"frozen_allow_local_core_sentinel": True, "core_executor": "docker"},
    ],
)
def test_frozen_settings_reject_incomplete_or_ineligible_execution(tmp_path, updates):
    with pytest.raises(ValidationError):
        config(tmp_path, **updates)


def test_first_launch_production_configuration_preserves_real_dependencies(tmp_path):
    updates = dict(
        environment="production",
        core_executor="docker",
        task_handoff_mode="outbox",
        task_receipt_mode="strict",
        frozen_analysis_enabled=True,
        evidence_promotion_enabled=True,
        automatic_analysis_enabled=True,
        symbol_imports_enabled=True,
        catalog_reviews_enabled=True,
        result_reviews_enabled=True,
        workspace_module_roles_enabled=True,
        catalog_source_enabled=True,
    )
    assert config(tmp_path, **updates).environment == "production"
    for field, value in (
        ("task_receipt_mode", "compat"),
        ("task_handoff_mode", "legacy"),
        ("frozen_core_enabled", False),
        ("frozen_analysis_enabled", False),
        ("evidence_promotion_enabled", False),
        ("core_executor", "fake"),
        ("external_bind_host", "8.8.8.8"),
    ):
        with pytest.raises(ValidationError):
            config(tmp_path, **{**updates, field: value})


@pytest.mark.parametrize("defect", ["run_bytes", "owner", "outside_pair", "pair_set", "raw_prefix"])
def test_worker_rejects_changed_or_foreign_inputs_before_subprocess(tmp_path, monkeypatch, defect):
    task = tmp_path / "task"
    assignment, pairs = staged(task)
    prefix = "runs/r/attempts/1"
    if defect == "run_bytes":
        with (task / "run.json").open("ab") as stream:
            stream.write(b" ")
    elif defect == "owner":
        assignment = replace(assignment, occurrence_id="occ_other")
    elif defect == "outside_pair":
        outside = tmp_path / "outside.pdb"
        outside.write_bytes(b"outside")
        pairs["a" * 64] = (pairs["a" * 64][0], outside)
    elif defect == "pair_set":
        pairs = {}
    else:
        prefix = "runs/../foreign"

    def forbidden(*args, **kwargs):
        pytest.fail("invalid input reached Core")

    monkeypatch.setattr("crashcap_worker.frozen_core._run", forbidden)
    with pytest.raises(CoreExecutionError) as caught:
        FrozenCoreExecutor(config(tmp_path)).execute(
            task, assignment, pairs, raw_object_prefix=prefix
        )
    assert caught.value.code == "INVALID_FROZEN_EVIDENCE"
    assert not (task / "execution.json").exists()


def test_worker_preserves_structured_process_failure(tmp_path, monkeypatch):
    task = tmp_path / "task"
    assignment, pairs = staged(task)

    def fail(command, **kwargs):
        assert command[1] == "analyze-frozen"
        assert "--allow-local-core-sentinel" not in command
        assert not (task / "results/frozen-output").exists()
        raise CoreExecutionError("FROZEN_SOURCE_FAILED", "http_503", returncode=1)

    monkeypatch.setattr("crashcap_worker.frozen_core._run", fail)
    with pytest.raises(CoreExecutionError) as caught:
        FrozenCoreExecutor(config(tmp_path)).execute(
            task, assignment, pairs, raw_object_prefix="runs/r/attempts/1"
        )
    assert caught.value.code == "FROZEN_SOURCE_FAILED"
    assert caught.value.returncode == 1
    assert not (task / "results/frozen-output/canonical.json").exists()


def test_docker_arguments_and_pair_paths_are_posix_on_any_host(tmp_path, monkeypatch):
    task = tmp_path / "task"
    assignment, pairs = staged(task)

    class Workspace:
        def __init__(self, settings, root, *, writable_directories):
            assert settings.core_executor == "docker"
            assert root == task.resolve()
            assert writable_directories == ("results",)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def run(self, args):
            for option in (
                "--dump",
                "--inspect",
                "--run",
                "--resolution-manifest",
                "--execution",
                "--output-dir",
            ):
                value = args[args.index(option) + 1]
                assert value.startswith("/work/") and "\\" not in value
            descriptor = json.loads((task / "execution.json").read_bytes())
            assert descriptor["pairs"]["a" * 64] == {"pe": "/work/pair.pe", "pdb": "/work/pair.pdb"}
            raise CoreExecutionError("CONTROL_STOP", "stop before starting a container")

    monkeypatch.setattr("crashcap_worker.frozen_core.DockerVolumeWorkspace", Workspace)
    with pytest.raises(CoreExecutionError) as caught:
        FrozenCoreExecutor(config(tmp_path, core_executor="docker")).execute(
            task, assignment, pairs, raw_object_prefix="runs/r/attempts/1"
        )
    assert caught.value.code == "CONTROL_STOP"


def test_stage_failure_removes_container_before_its_volume(tmp_path, monkeypatch):
    from subprocess import CompletedProcess

    commands = []
    monkeypatch.setattr("crashcap_worker.core_runner._verify_core_image", lambda settings: None)

    def run(command, **kwargs):
        commands.append(command)
        return CompletedProcess(command, 0, "", "")

    def fail_metadata(self):
        raise CoreExecutionError("CORE_STAGE_FAILED", "controlled metadata copy failure")

    monkeypatch.setattr("crashcap_worker.core_runner._run", run)
    monkeypatch.setattr(DockerVolumeWorkspace, "_prepare_writable_directories", fail_metadata)
    workspace = DockerVolumeWorkspace(
        config(tmp_path, core_executor="docker"), tmp_path, writable_directories=("results",)
    )
    with pytest.raises(CoreExecutionError, match="controlled metadata"), workspace:
        pytest.fail("failed staging reached runtime")
    stage_remove = commands.index(["docker", "rm", "-f", workspace.stage])
    volume_remove = commands.index(["docker", "volume", "rm", "-f", workspace.volume])
    assert stage_remove < volume_remove
