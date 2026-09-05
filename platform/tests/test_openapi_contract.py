from __future__ import annotations

import hashlib
from pathlib import Path

from crashcap_api.response_contracts import install_canonical_openapi_contract
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "analysis-result-v2.0.schema.json"


def test_openapi_contract_is_identical_for_lf_and_crlf_worktrees(tmp_path: Path) -> None:
    canonical_bytes = (ROOT / "contracts" / CONTRACT).read_bytes().replace(b"\r\n", b"\n")
    documents = []
    for name, content in (
        ("unix", canonical_bytes),
        ("windows", canonical_bytes.replace(b"\n", b"\r\n")),
    ):
        schema_root = tmp_path / name
        schema_root.mkdir()
        (schema_root / CONTRACT).write_bytes(content)
        app = FastAPI()
        install_canonical_openapi_contract(app, schema_root)
        documents.append(app.openapi())

    assert documents[0] == documents[1]
    contract = documents[0]["components"]["schemas"]["CanonicalAnalysisResult"]
    assert contract["x-crashcap-source-sha256"] == hashlib.sha256(canonical_bytes).hexdigest()
