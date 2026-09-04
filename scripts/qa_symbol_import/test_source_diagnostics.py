from __future__ import annotations

import unittest

from source_diagnostics import source_outcomes


class DiagnosticTests(unittest.TestCase):
    def test_unknown_failure_is_not_assumed_transient(self):
        module = {
            "debug_status": "fetching_failed",
            "candidates": [
                {
                    "source": "pair:a",
                    "location": "http://internal/a/debuginfo",
                    "download": {
                        "status": "error",
                        "details": "temporary system_symbol_failed",
                    },
                }
            ],
        }
        result = source_outcomes(module, [])
        self.assertEqual(result[0]["failure_class"], "unknown")
        result = source_outcomes(
            module,
            [
                {
                    "path": "/a/debuginfo",
                    "status": 503,
                    "failure_class": "transient",
                    "reason": "upstream_unavailable",
                }
            ],
        )
        self.assertEqual(result[0]["failure_class"], "transient")

    def test_integrity_failure_is_permanent_despite_server_status(self):
        module = {
            "candidates": [
                {
                    "source": "pair:a",
                    "location": "http://internal/a/debuginfo",
                    "download": {"status": "error"},
                }
            ]
        }
        result = source_outcomes(
            module,
            [
                {
                    "path": "/a/debuginfo",
                    "status": 503,
                    "failure_class": "permanent",
                    "reason": "integrity_failed",
                }
            ],
        )
        self.assertEqual(result[0]["failure_class"], "permanent")
        self.assertEqual(result[0]["reason"], "integrity_failed")

    def test_download_success_and_decode_failure_are_separate(self):
        module = {
            "debug_status": "malformed",
            "candidates": [
                {
                    "source": "pair:a",
                    "location": "http://internal/a/debuginfo",
                    "download": {"status": "ok"},
                }
            ],
        }
        result = source_outcomes(module, [])
        self.assertEqual(result[0]["outcome"], "found")
        self.assertEqual(result[1]["failure_class"], "permanent")

    def test_notfound_is_permanent_not_a_transient_system_exception(self):
        module = {
            "debug_status": "missing",
            "candidates": [
                {
                    "source": "pair:a",
                    "location": "http://internal/a/debuginfo",
                    "download": {"status": "notfound"},
                }
            ],
        }
        self.assertEqual(source_outcomes(module, [])[0]["failure_class"], "permanent")


if __name__ == "__main__":
    unittest.main()
