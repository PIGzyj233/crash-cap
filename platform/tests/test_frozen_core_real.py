"""Owned-service lane, explicitly run by qualify_native_sources.py."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from crashcap_api.config import Settings
from crashcap_api.frozen_inputs import canonical_bytes, digest, frozen_run_key
from crashcap_worker.core_runner import CoreExecutionError, DockerVolumeWorkspace, _run
from crashcap_worker.frozen_core import FrozenAssignment, FrozenCoreExecutor

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["local", "docker"])
@pytest.mark.skipif(
    not os.getenv("QAI_NATIVE_SOURCE_ENDPOINT"), reason="requires owned native source service"
)
def test_worker_executes_real_core_and_validates_retained_bytes(tmp_path, mode):
    if mode == "docker" and not os.getenv("QAI_NATIVE_CORE_IMAGE"):
        pytest.skip("requires an explicitly built qualification Core image")
    native = ROOT / "target/qa-symbol-import/native-source"
    baseline = ROOT / "target/qa-symbol-import/frozen-context"
    fixture = ROOT / "fixtures/p0-b01-null-read/generated"
    metadata = json.loads((baseline / "qualification.json").read_text())
    values = Settings.for_test(tmp_path).model_dump()
    values.update(
        core_executor="local",
        core_command=str(
            ROOT / "target/debug" / ("dmp-core.exe" if os.name == "nt" else "dmp-core")
        ),
        frozen_core_enabled=True,
        frozen_allow_local_core_sentinel=True,
        core_image_digest="sha256:" + "0" * 64,
        frozen_symbolicator_url=os.environ["QAI_NATIVE_SOURCE_ENDPOINT"],
        frozen_pair_source_root=os.environ["QAI_NATIVE_SOURCE_ROOT"],
        frozen_symbolicator_image_digest=os.environ["QAI_NATIVE_SOURCE_IMAGE_DIGEST"],
        symbolicator_version=os.environ["QAI_NATIVE_SOURCE_VERSION"],
    )
    if mode == "docker":
        values.update(
            core_executor="docker",
            core_image=os.environ["QAI_NATIVE_CORE_IMAGE"],
            core_image_digest=os.environ["QAI_NATIVE_CORE_IMAGE_DIGEST"],
            frozen_allow_local_core_sentinel=False,
            core_network="bridge",
            frozen_symbolicator_url=f"http://host.docker.internal:{urlsplit(os.environ['QAI_NATIVE_SOURCE_ENDPOINT']).port}",
        )
    executor = FrozenCoreExecutor(Settings(**values))
    # Retain the execution and raw output alongside the other qualification evidence.
    import uuid

    task = native / (f"worker-{mode}-" + uuid.uuid4().hex)
    task.mkdir()
    for source, name in (
        (baseline / "run.json", "run.json"),
        (baseline / "manifest.json", "resolution-manifest.json"),
        (baseline / "inspect.json", "inspect.json"),
        (fixture / "null-read.dmp", "dump.dmp"),
        (fixture / "null_read_target.exe", "pair.pe"),
        (fixture / "null_read_target.pdb", "pair.pdb"),
    ):
        shutil.copyfile(source, task / name)
    assignment = FrozenAssignment(
        "run_frozen_context", "occ_fixture", "wsp_fixture", metadata["run_sha256"]
    )
    if mode == "docker":
        # Seal a NEW fixture Run for the actual Linux image. Never mutate the
        # baseline Run or pretend an image change preserves semantic context.
        docker_run = json.loads((task / "run.json").read_bytes())
        docker_run["run_id"] = "run_frozen_worker_docker"
        docker_run["context"]["core_image_digest"] = values["core_image_digest"]
        docker_run["context_sha256"] = digest(docker_run["context"])
        docker_run["idempotency_key"] = frozen_run_key(docker_run)
        encoded = canonical_bytes(docker_run)
        (task / "run.json").write_bytes(encoded)
        assignment = replace(
            assignment,
            run_id=docker_run["run_id"],
            object_sha256=hashlib.sha256(encoded).hexdigest(),
        )
    prefix = f"qualification/{task.name}/attempts/1"
    pairs = {metadata["pair_id"]: (task / "pair.pe", task / "pair.pdb")}
    output = executor.execute(task, assignment, pairs, raw_object_prefix=prefix)
    resources_removed = None
    if mode == "docker":
        workspace = DockerVolumeWorkspace(executor.settings, task)
        volumes = _run(
            ["docker", "volume", "ls", "--format", "{{.Name}}"], timeout=30
        ).stdout.splitlines()
        containers = _run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"], timeout=30
        ).stdout.splitlines()
        assert workspace.volume not in volumes
        assert workspace.stage not in containers and workspace.extract not in containers
        resources_removed = True
    assert output.canonical_bytes == output.canonical_path.read_bytes()
    assert output.canonical["analysis_id"] == assignment.run_id
    assert any(
        "trigger_null_read" in (f["function"] or "") and f["line"] == 76
        for t in output.canonical["threads"]
        for f in t["frames"]
    )
    assert all(
        hashlib.sha256(path.read_bytes()).hexdigest() == output.raw_sha256[key]
        for key, path in output.raw.items()
    )
    with pytest.raises(CoreExecutionError):
        executor.execute(
            task, replace(assignment, workspace_id="wsp_foreign"), pairs, raw_object_prefix=prefix
        )
    with pytest.raises(CoreExecutionError):
        executor.execute(task, assignment, pairs, raw_object_prefix=prefix)
    run = json.loads((task / "run.json").read_bytes())
    manifest = json.loads((task / "resolution-manifest.json").read_bytes())
    inspect = json.loads((task / "inspect.json").read_bytes())
    inputs = {
        name: (task / name).read_bytes()
        for name in ("run.json", "resolution-manifest.json", "inspect.json", "execution.json")
    }
    cases = []
    for defect in (
        "assignment",
        "dump_facts",
        "context",
        "role",
        "selection",
        "foreign_build",
        "diagnostic_hash",
        "raw_input",
        "schema",
    ):
        changed = copy.deepcopy(output.canonical)
        raw_path = None
        if defect == "assignment":
            changed["occurrence_id"] = "occ_other"
        elif defect == "dump_facts":
            changed["dump"]["blob_id"] = "blob_other"
        elif defect == "context":
            changed["symbol_resolution"]["context_sha256"] = "1" * 64
        elif defect == "role":
            changed["modules"][0].update(role="dependency", in_app=False)
        elif defect == "selection":
            changed["modules"][0]["selection"]["candidate_evidence"]["sha256"] = "1" * 64
        elif defect == "foreign_build":
            changed["build_resolution"]["resolved_build_id"] = "bld_foreign"
        elif defect == "diagnostic_hash":
            changed["modules"][0]["source_outcomes"][0]["diagnostic_ref"]["sha256"] = "1" * 64
        elif defect == "raw_input":
            raw_path = task / "results/frozen-output/raw/run.json"
            raw_path.write_bytes(inputs["run.json"] + b" ")
        else:
            changed["schema_version"] = "1.0"
        output.canonical_path.write_text(json.dumps(changed), encoding="utf-8")
        try:
            with pytest.raises(CoreExecutionError) as caught:
                executor._validate_output(
                    task / "results/frozen-output", prefix, run, manifest, inspect, inputs
                )
            assert caught.value.code == "INVALID_FROZEN_EVIDENCE"
            cases.append(defect)
        finally:
            output.canonical_path.write_bytes(output.canonical_bytes)
            if raw_path:
                raw_path.write_bytes(inputs["run.json"])
    receipt = {
        "status": "PASS",
        "executor": mode,
        "task_resources_removed": resources_removed,
        "core_image_digest": values["core_image_digest"],
        "task_dir": str(task),
        "run_sha256": assignment.object_sha256,
        "canonical_sha256": hashlib.sha256(output.canonical_bytes).hexdigest(),
        "raw_sha256": output.raw_sha256,
        "rejected_output_controls": cases,
        "not_proven": [
            "durable task/lease",
            "object-store upload",
            "planner/catalog",
            "promotion",
        ],
    }
    name = "worker-qualification.json" if mode == "local" else "worker-docker-qualification.json"
    (native / name).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
