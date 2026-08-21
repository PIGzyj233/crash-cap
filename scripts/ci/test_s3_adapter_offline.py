#!/usr/bin/env python3
"""Offline tests for the replaceable S3 adapter surface.

This test intentionally does not install boto3 or contact an endpoint.  A tiny
module stub lets it import the adapter and exercise the streaming hash helper;
the qualification runner remains the separate Docker-backed S3 job.
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = ROOT / "qualification" / "s3" / "adapter.py"


def load_adapter():
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.client = lambda *_args, **_kwargs: None
    botocore_stub = types.ModuleType("botocore")
    config_stub = types.ModuleType("botocore.config")
    config_stub.Config = lambda **kwargs: kwargs
    botocore_stub.config = config_stub
    previous = {name: sys.modules.get(name) for name in ("boto3", "botocore", "botocore.config")}
    sys.modules.update({"boto3": boto3_stub, "botocore": botocore_stub, "botocore.config": config_stub})
    try:
        spec = importlib.util.spec_from_file_location("crash_cap_s3_adapter_offline", ADAPTER_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load adapter module")
        module = importlib.util.module_from_spec(spec)
        previous_module = sys.modules.get(spec.name)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if "previous_module" in locals() and previous_module is not None:
            sys.modules[spec.name] = previous_module
        elif "spec" in locals() and spec is not None:
            sys.modules.pop(spec.name, None)
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


class GuardedBody:
    def iter_chunks(self, *, chunk_size: int):
        self.chunk_size = chunk_size
        yield b"stream-"
        yield b"only"

    def read(self, *_args, **_kwargs):
        raise AssertionError("offline hash helper must not call read()")


class AdapterOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = load_adapter()
        cls.source = ADAPTER_PATH.read_text(encoding="utf-8").lower()

    def test_stream_hash_uses_bounded_iter_chunks(self):
        digest, size, max_chunk = self.adapter.stream_sha256(GuardedBody(), chunk_size=4)
        self.assertEqual(size, len(b"stream-only"))
        self.assertEqual(max_chunk, len(b"stream-"))
        self.assertEqual(
            digest,
            "c28bbc11b58e47d10100c06720f58d623ba253e4ef2c2cd7cd241226481b61c1",
        )

    def test_adapter_contains_no_vendor_management_surface(self):
        for forbidden in ("rustfs", "minio", "console", "rpc_secret", "admin", "/v3/"):
            self.assertNotIn(forbidden, self.source)

    def test_adapter_exposes_required_standard_operations(self):
        required = (
            "create_bucket",
            "put_object",
            "head_object",
            "get_object",
            "generate_presigned_url",
            "create_multipart",
            "complete_multipart",
            "abort_multipart",
            "put_bucket_lifecycle",
            "put_bucket_encryption",
        )
        for name in required:
            self.assertTrue(hasattr(self.adapter.S3Adapter, name), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
