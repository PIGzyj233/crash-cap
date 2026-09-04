"""Executable S0 invariants. Synthetic vectors do not claim Symbolicator qualification."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_drafts
from jsonschema import Draft202012Validator
from protocol import (
    advance_target,
    canonical_bytes,
    digest,
    evidence_fingerprint,
    pair_id,
    run_key,
    select_candidates,
    validate_manifest,
)
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
DRAFTS = ROOT / "contracts/drafts/qa-symbol-import"
IDENTITY = {
    "code_id": "6a87124ac8000",
    "debug_id": "5295c1f4535d4f8aa0b1989805198bb815",
    "architecture": "x86_64",
}


def candidate(pe="a", pdb="b", **extra):
    return {
        "identity": IDENTITY,
        "pe_raw_sha256": pe * 64,
        "pdb_raw_sha256": pdb * 64,
        "validation": "verified",
        "availability": "active",
        **extra,
    }


def manifest(candidates=None, complete=True):
    selection = select_candidates(
        IDENTITY,
        candidates if candidates is not None else [candidate()],
        complete=complete,
    )
    reason = {
        "unique": "unique",
        "none": "missing",
        "conflict": "identity_conflict",
        "unavailable": "withdrawn",
        "indeterminate": "enumeration_failed",
    }[selection["state"]]
    selection.update(
        {
            "module_index": 0,
            "reason": reason,
            "candidate_evidence": {
                "object_key": "frozen/candidates",
                "sha256": "c" * 64,
            },
            "review_refs": [],
        }
    )
    return {
        "schema_version": "resolution-manifest-v1",
        "dump_sha256": "d" * 64,
        "inspector_version": "inspect-v1",
        "inspect_sha256": "e" * 64,
        "selection_version": "pair-selection-v1",
        "catalog_revision": 7,
        "modules": [selection],
    }


class ProtocolTests(unittest.TestCase):
    def test_regeneration_preserves_generated_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contracts").mkdir()
            for name in ("analysis-result-v1.schema.json", "source-bundle-v1.schema.json"):
                shutil.copyfile(ROOT / "contracts" / name, root / "contracts" / name)
            output = root / "contracts/drafts/qa-symbol-import"
            with patch.object(build_drafts, "ROOT", root), patch.object(build_drafts, "OUT", output):
                build_drafts.main()
            manually_maintained = {
                "result-review-audit-v1.schema.json",
                "result-review-request-v1.schema.json",
            }
            self.assertEqual(
                {p.name for p in output.glob("*.schema.json")},
                {p.name for p in DRAFTS.glob("*.schema.json")} - manually_maintained,
            )
            for generated in output.glob("*.schema.json"):
                self.assertEqual(json.loads(generated.read_text()),
                                 json.loads((DRAFTS / generated.name).read_text()), generated.name)
            self.assertEqual(
                json.loads((root / "contracts/analysis-result-v1.1.schema.json").read_text()),
                json.loads((ROOT / "contracts/analysis-result-v1.1.schema.json").read_text()),
            )

    def test_hash_encoding(self):
        self.assertEqual(
            canonical_bytes({"z": "测试", "a": 1}), '{"a":1,"z":"测试"}'.encode()
        )
        self.assertEqual(
            pair_id("a" * 64, "b" * 64),
            "47ef4d250a9240d7e9432186ccde2ce0a2ec5f8ba803dc1afea644eecb02c019",
        )
        for invalid in (float("nan"), 1.2, 2**53, {"非ASCII键": 1}):
            with self.assertRaises(ValueError):
                canonical_bytes(invalid)

    def test_content_grouping_and_contradictions(self):
        self.assertEqual(
            select_candidates(
                IDENTITY,
                [candidate(), candidate(origin="other_workspace")],
                complete=True,
            )["state"],
            "unique",
        )
        self.assertEqual(
            select_candidates(
                IDENTITY, [candidate(), candidate(pe="f")], complete=True
            )["state"],
            "conflict",
        )
        wrong = {**IDENTITY, "code_id": "123456789"}
        self.assertEqual(
            select_candidates(
                IDENTITY,
                [candidate(), candidate(pe="f", identity=wrong)],
                complete=True,
            )["state"],
            "unique",
        )

    def test_incomplete_enumeration_never_unique(self):
        self.assertEqual(
            select_candidates(IDENTITY, [candidate()], complete=False)["state"],
            "indeterminate",
        )
        self.assertEqual(
            select_candidates(
                IDENTITY, [candidate(), candidate(validation="pending")], complete=True
            )["state"],
            "indeterminate",
        )
        self.assertEqual(
            select_candidates(
                IDENTITY,
                [candidate(identity={**IDENTITY, "debug_id": None})],
                complete=True,
            )["state"],
            "indeterminate",
        )

    def test_withdrawal_and_inconsistent_snapshot(self):
        self.assertEqual(
            select_candidates(
                IDENTITY, [candidate(availability="withdrawn")], complete=True
            )["state"],
            "unavailable",
        )
        self.assertEqual(
            select_candidates(
                IDENTITY,
                [candidate(), candidate(availability="withdrawn")],
                complete=True,
            )["state"],
            "indeterminate",
        )

    def test_relevant_and_full_digests_are_distinct(self):
        before = manifest()
        after = copy.deepcopy(before)
        after["catalog_revision"] += 1
        after["modules"][0]["candidate_evidence"]["sha256"] = "f" * 64
        self.assertEqual(evidence_fingerprint(before), evidence_fingerprint(after))
        self.assertNotEqual(digest(before), digest(after))
        self.assertEqual(
            evidence_fingerprint(before),
            evidence_fingerprint(manifest([candidate(), candidate(origin="extra")])),
        )
        self.assertNotEqual(
            evidence_fingerprint(before),
            evidence_fingerprint(manifest([candidate(), candidate(pe="f")])),
        )

    def test_aba_and_attempts(self):
        a = evidence_fingerprint(manifest())
        b = evidence_fingerprint(manifest([candidate(), candidate(pe="f")]))
        generation = advance_target(None, a, 0)
        self.assertEqual(advance_target(a, a, generation), 1)
        generation = advance_target(a, b, generation)
        generation = advance_target(b, a, generation)
        self.assertEqual(generation, 3)
        keys = {
            run_key(
                occurrence_id="occ_a",
                fingerprint=a,
                context_sha256="c" * 64,
                generation=g,
                attempt=t,
            )
            for g, t in [(1, 0), (3, 0), (3, 1)]
        }
        self.assertEqual(len(keys), 3)

    def test_schema_pack_and_manifest_negatives(self):
        schemas = [
            json.loads(p.read_text()) for p in sorted(DRAFTS.glob("*.schema.json"))
        ]
        self.assertEqual(
            {p.name for p in DRAFTS.glob("*.schema.json")},
            {name + ".schema.json" for name in (
                "analysis-context-v2", "analysis-demand-v1", "analysis-result-v1.1",
                "analysis-run-v2", "comparison-decision-v1", "comparison-evidence-v1",
                "resolution-manifest-v1",
                "result-review-audit-v1", "result-review-request-v1",
                "symbol-import-request-v1", "symbol-import-result-v1", "task-message-v1.2",
            )},
        )
        registry = Registry().with_resources(
            (s["$id"], Resource.from_contents(s)) for s in schemas
        )
        for schema in schemas:
            Draft202012Validator.check_schema(schema)
        schema = next(
            s for s in schemas if "resolution-manifest-v1.schema.json" in s["$id"]
        )
        validator = Draft202012Validator(schema, registry=registry)
        for value in [
            manifest(),
            manifest([]),
            manifest([candidate(), candidate(pe="f")]),
            manifest(complete=False),
            manifest([candidate(availability="withdrawn")]),
        ]:
            validator.validate(value)
        bad = manifest(complete=False)
        bad["modules"][0]["selected_pair_id"] = pair_id("a" * 64, "b" * 64)
        self.assertFalse(validator.is_valid(bad))
        bad = manifest()
        bad["workspace_id"] = "must_not_leak"
        self.assertFalse(validator.is_valid(bad))

    def test_manifest_semantics(self):
        validate_manifest(manifest())
        bad = manifest()
        bad["modules"][0]["selected_pair_id"] = "f" * 64
        with self.assertRaises(ValueError):
            validate_manifest(bad)
        bad = manifest()
        bad["modules"][0]["reason"] = "withdrawn"
        with self.assertRaises(ValueError):
            validate_manifest(bad)

    def test_task_version_is_separate_from_blob_publication(self):
        task = {
            "schema_version": "1.2",
            "task_type": "plan_analysis_demand",
            "demand_id": "dem_example",
            "attempt_id": "att_example",
            "queue": "verify",
        }
        new = json.loads((DRAFTS / "task-message-v1.2.schema.json").read_text())
        Draft202012Validator(new).validate(task)
        for name in ("task-message-v1", "task-message-v1.1"):
            old = json.loads((ROOT / "contracts" / f"{name}.schema.json").read_text())
            self.assertFalse(Draft202012Validator(old).is_valid(task))


if __name__ == "__main__":
    unittest.main()
