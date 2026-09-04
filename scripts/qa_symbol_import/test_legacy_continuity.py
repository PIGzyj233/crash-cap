from __future__ import annotations

import copy
import unittest

from legacy_continuity import qualify_legacy


class LegacyContinuityTests(unittest.TestCase):
    def setUp(self):
        self.inspect = {
            "process": {"architecture": "x86_64"},
            "exception": {
                "address": "0x1001",
                "thread_id": 7,
                "code": "0xc0000005",
                "access_type": "write",
                "fault_address": "0x0",
            },
            "modules": [
                {
                    "image_base": "0x1000",
                    "image_size": 256,
                    "code_id": "123456789",
                    "debug_id": "a" * 32 + "1",
                }
            ],
        }
        self.canonical = {
            "schema_version": "1.0",
            "crash": {
                "type": "crash",
                "address": "0x1001",
                "thread_id": 7,
                "exception_code": "0xC0000005",
                "access_type": "write",
            },
            "threads": [
                {
                    "id": 7,
                    "is_crashing": True,
                    "frames": [
                        {
                            "instruction_addr": "0x1001",
                            "trust": "context",
                            "in_app": True,
                            "function": "old",
                            "file": "a.cpp",
                            "line": 5,
                        }
                    ],
                }
            ],
        }
        self.raw = {
            "threads": [
                {"id": 7, "frames": [{"instruction": 4097, "trust": "context"}]}
            ]
        }

    def test_verified_context_and_fault_anchor(self):
        before = copy.deepcopy((self.canonical, self.raw))
        result = qualify_legacy(
            self.canonical, self.inspect, self.raw, dump_available=True
        )
        self.assertEqual(result["anchor_status"], "verified")
        self.assertEqual(result["fault_anchor"]["rva"], "0x1")
        self.assertEqual(result["fault_anchor"]["fault_address"], "0x0")
        self.assertEqual(len(result["business_anchors"]), 1)
        self.assertFalse(result["automatic_promotion"])
        self.assertEqual(before, (self.canonical, self.raw))

    def test_folded_cfi_is_not_invented(self):
        self.canonical["threads"][0]["frames"][0]["trust"] = "cfi"
        self.raw["threads"][0]["frames"][0]["trust"] = "cfi"
        result = qualify_legacy(
            self.canonical, self.inspect, self.raw, dump_available=True
        )
        self.assertEqual(result["anchor_status"], "incomparable")
        self.assertIn("legacy_unwind_provenance_missing", result["reasons"])
        self.assertEqual(result["route"], "explicit_engine_upgrade_or_review")

    def test_missing_raw_and_expired_withdrawn_basis(self):
        result = qualify_legacy(
            self.canonical,
            self.inspect,
            None,
            dump_available=False,
            basis_withdrawn=True,
        )
        self.assertEqual(result["route"], "basis_withdrawn_cannot_recompute")
        self.assertIn("raw_unwind_unavailable", result["reasons"])

    def test_explicit_cfi_scan_does_not_become_a_reliable_business_anchor(self):
        self.canonical["threads"][0]["frames"][0]["trust"] = "cfi"
        self.raw["threads"][0]["frames"][0].update(
            {"trust": "cfi", "unwind_method": "cfi_scan"}
        )
        result = qualify_legacy(
            self.canonical, self.inspect, self.raw, dump_available=True
        )
        self.assertEqual(result["anchor_status"], "verified")
        self.assertEqual(result["business_anchors"], [])

    def test_repeated_rvas_remain_separate_physical_anchors(self):
        self.canonical["threads"][0]["frames"] *= 2
        self.raw["threads"][0]["frames"] *= 2
        result = qualify_legacy(
            self.canonical, self.inspect, self.raw, dump_available=True
        )
        self.assertEqual(len(result["business_anchors"]), 2)
        self.assertEqual(result["anchor_status"], "verified")

    def test_fault_and_alignment_mismatch_do_not_pass(self):
        self.canonical["crash"]["address"] = "0x0"
        result = qualify_legacy(
            self.canonical, self.inspect, self.raw, dump_available=True
        )
        self.assertIn("fault_anchor_mismatch", result["reasons"])
        self.raw["threads"][0]["frames"][0]["instruction"] += 1
        result = qualify_legacy(
            self.canonical, self.inspect, self.raw, dump_available=True
        )
        self.assertIn("physical_frame_alignment_mismatch", result["reasons"])


if __name__ == "__main__":
    unittest.main()
