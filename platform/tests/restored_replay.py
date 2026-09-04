"""Replay immutable Run bytes using only restored metadata and payload."""

import hashlib
import json
from copy import deepcopy

from crashcap_api.frozen_inputs import canonical_bytes
from crashcap_api.models import AnalysisRun, Occurrence
from crashcap_api.services.catalog_materials import materialize_catalog_file, select_material
from crashcap_worker.frozen_core import FrozenAssignment, FrozenCoreExecutor

from .restored_symbolicator import restored_symbolicator


def compare_replay(baseline, output, store, old_root, new_root):
    """Require identical facts; validate transport evidence before rebasing its ref."""
    compared = deepcopy(output.canonical)
    evidence = {}
    for before, after in zip(baseline["modules"], compared["modules"], strict=True):
        for old, new in zip(before["source_outcomes"], after["source_outcomes"], strict=True):
            old_ref, new_ref = old["diagnostic_ref"], new["diagnostic_ref"]
            if old_ref is None or new_ref is None:
                assert old_ref == new_ref
                continue
            key = old_ref["object_key"]
            assert key == new_ref["object_key"]
            if key not in evidence:
                original = b"".join(store.stream(key))
                replayed = output.raw[key].read_bytes()
                assert hashlib.sha256(original).hexdigest() == old_ref["sha256"]
                assert hashlib.sha256(replayed).hexdigest() == new_ref["sha256"]
                left, right = json.loads(original), json.loads(replayed)
                for diagnostic, root in ((left, old_root), (right, new_root)):
                    # Request/response byte hashes change with the isolated HTTP port.
                    assert len(bytes.fromhex(diagnostic.pop("request_sha256"))) == 32
                    attempts = diagnostic.pop("attempts")
                    assert attempts
                    for index, attempt in enumerate(attempts):
                        assert attempt["status"] == 200
                        assert attempt["reason"] is None
                        assert attempt["operation"] == ("post:1" if index == 0 else f"poll:{index}")
                        assert len(bytes.fromhex(attempt.pop("response_sha256"))) == 32
                    assert diagnostic["failure"] is None
                    for module in diagnostic["response"]["modules"]:
                        for candidate in module["candidates"]:
                            location = candidate["location"]
                            assert location.startswith(root + "/")
                            candidate["location"] = location[len(root):]
                assert left == right, key
                evidence[key] = {
                    "original_sha256": old_ref["sha256"],
                    "replayed_sha256": new_ref["sha256"],
                    "replayed_path": str(output.raw[key]),
                }
            new["diagnostic_ref"] = deepcopy(old_ref)
    assert compared == baseline
    return evidence


def replay_restored(settings, live, receipt):
    with restored_symbolicator(settings, live, receipt) as (
        engine_settings,
        sessions,
        store,
        events,
    ):
        with sessions() as session:
            occurrence = session.query(Occurrence).one()
            run = session.get(AnalysisRun, occurrence.current_run_id)
            spec = dict(run.run_spec)
            original = b"".join(store.stream(run.result_object_key))
            prefix = run.result_object_key.rsplit("/", 1)[0]
        task = settings.object_store_local_root.parent.with_name("qai-replay") / live["output"].name
        task.mkdir(parents=True)
        run_bytes = canonical_bytes(spec)
        (task / "run.json").write_bytes(run_bytes)
        for key, filename in (
            ("dump", "dump.dmp"),
            ("inspect", "inspect.json"),
            ("resolution_manifest", "resolution-manifest.json"),
        ):
            store.download_file(spec[key]["object_key"], task / filename)
        manifest = json.loads((task / "resolution-manifest.json").read_bytes())
        pairs = {}
        for row in manifest["modules"]:
            pair_id = row["selected_pair_id"]
            if pair_id is None or pair_id in pairs:
                continue
            paths = []
            for kind in ("pe", "pdb"):
                with sessions() as session:
                    material = select_material(
                        session, pair_id, row["identity"]["debug_id"], kind, max_locations=32
                    )
                path = task / f"{len(pairs)}.{kind}"
                materialize_catalog_file(store, material, path)
                paths.append(path)
            pairs[pair_id] = tuple(paths)
        assert not spec["source_bundle_locations"], "C08 recovery fixture has no source bundle"
        output = FrozenCoreExecutor(engine_settings).execute(
            task,
            FrozenAssignment(
                run.id,
                occurrence.id,
                occurrence.workspace_id,
                hashlib.sha256(run_bytes).hexdigest(),
            ),
            pairs,
            raw_object_prefix=prefix,
        )
        (live["output"] / "restore/replayed-canonical.json").write_bytes(output.canonical_bytes)
        baseline = json.loads(original)
        evidence = compare_replay(
            baseline, output, store, live["source_root"], engine_settings.frozen_pair_source_root
        )
        for pair_id in pairs:
            for suffix in ("/debuginfo", "/executable"):
                assert any(
                    pair_id in event["path"]
                    and event["path"].endswith(suffix)
                    and event["status"] in (200, 206)
                    for event in events
                )
        receipt.update(
            cold_cache_replay="PASS",
            replay_run_id=run.id,
            original_canonical_sha256=hashlib.sha256(original).hexdigest(),
            replayed_canonical_sha256=hashlib.sha256(output.canonical_bytes).hexdigest(),
            replayed_pair_ids=sorted(pairs),
            transport_evidence=evidence,
            canonical_comparison="identical except verified transport diagnostic hashes",
        )
