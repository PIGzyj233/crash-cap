from __future__ import annotations

import copy
import unittest

from partitioned_source import collect_partition, plan_requests


class PartitionTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "modules": [
                {"image_addr": 4096, "image_size": 256},
                {"image_addr": 8192, "image_size": 256},
            ],
            "stacktraces": [
                {
                    "frames": [
                        {"instruction_addr": "0x1001"},
                        {"instruction_addr": "0x2001"},
                        {"instruction_addr": "0x1001"},
                    ]
                }
            ],
        }
        self.selections = [
            {"state": "unique", "selected_pair_id": "a"},
            {"state": "unique", "selected_pair_id": "b"},
        ]
        self.sources = {"a": {"id": "managed-a"}, "b": {"id": "managed-b"}}

    def test_shared_identity_different_pairs_never_share_request(self):
        jobs, blocked = plan_requests(self.payload, self.selections, self.sources)
        self.assertEqual(blocked, [])
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["frame_refs"], [(0, 0, 0), (0, 2, 0)])
        self.assertEqual(jobs[1]["request"]["sources"], [self.sources["b"]])
        self.assertEqual(len(jobs[0]["request"]["modules"]), 1)

    def test_conflict_does_not_enter_public_request(self):
        for state in ("conflict", "unavailable", "indeterminate"):
            self.selections[0] = {"state": state, "selected_pair_id": None}
            jobs, blocked = plan_requests(
                self.payload,
                self.selections,
                self.sources,
                public_sources=[{"id": "public"}],
            )
            self.assertEqual(blocked, [0])
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["module_indexes"], [1])
            self.assertEqual(jobs[0]["request"]["sources"], [self.sources["b"]])

    def test_inline_and_recursion_retain_physical_provenance(self):
        jobs, _ = plan_requests(self.payload, self.selections, self.sources)
        result = {
            "stacktraces": [
                {
                    "frames": [
                        {
                            "original_index": 0,
                            "function": "inline",
                            "instruction_addr": "0x1001",
                        },
                        {
                            "original_index": 0,
                            "function": "outer",
                            "instruction_addr": "0x1001",
                        },
                    ]
                },
                {
                    "frames": [
                        {
                            "original_index": 0,
                            "function": "recursive",
                            "instruction_addr": "0x1001",
                        }
                    ]
                },
            ]
        }
        outputs = collect_partition(jobs[0], result)
        self.assertEqual([o["frame_index"] for o in outputs], [0, 2])
        self.assertEqual(len(outputs[0]["symbols"]), 2)
        bad = copy.deepcopy(result)
        bad["stacktraces"][0]["frames"][0]["original_index"] = 1
        with self.assertRaises(ValueError):
            collect_partition(jobs[0], bad)
        bad = copy.deepcopy(result)
        bad["stacktraces"][0]["frames"][0]["instruction_addr"] = "0x1000"
        with self.assertRaises(ValueError):
            collect_partition(jobs[0], bad)

    def test_missing_selection_and_ambiguous_range_fail_closed(self):
        with self.assertRaises(ValueError):
            plan_requests(self.payload, self.selections[:1], self.sources)
        self.payload["modules"][1]["image_addr"] = 4096
        with self.assertRaises(ValueError):
            plan_requests(self.payload, self.selections, self.sources)


if __name__ == "__main__":
    unittest.main()
