from __future__ import annotations

import hashlib
from typing import Any

from crashcap_api.build_publications import canonical_fingerprint


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest(*, role: str = "entrypoint", version: str = "1.0.0") -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "product": "Local Publisher Test",
        "version": version,
        "channel": "local",
        "commit": "0123456789abcdef",
        "architecture": "x86_64",
        "compiler": "msvc",
        "toolchain": "vs2022",
        "modules": [
            {
                "code_file": "app.exe",
                "debug_file": "app.pdb",
                "role": role,
            }
        ],
    }


def _publication(
    pe: bytes,
    pdb: bytes,
    *,
    origin: str = "local",
    client_id: str = "local:0123456789abcdef:release",
    role: str = "entrypoint",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "origin": origin,
        "client_publication_id": client_id,
        "client_version": "crashcap/1.0.0",
        "git": {
            "revision": "0123456789abcdef",
            "worktree_state": "dirty",
        },
        "manifest": _manifest(role=role),
        "artifacts": [
            {
                "module_code_file": "app.exe",
                "kind": "pe",
                "logical_name": "app.exe",
                "size": len(pe),
                "sha256": _sha(pe),
            },
            {
                "module_code_file": "app.exe",
                "kind": "pdb",
                "logical_name": "app.pdb",
                "size": len(pdb),
                "sha256": _sha(pdb),
            },
        ],
    }


def _enable(harness: Any) -> None:
    harness.app.state.settings.build_publications_enabled = True


def _upload_expected(harness: Any, build_id: str, item: dict[str, Any], payload: bytes) -> str:
    initialized = harness.client.post(
        f"/api/v1/builds/{build_id}/artifacts/uploads:init",
        json={
            "file_kind": item["kind"],
            "filename": item["logical_name"],
            "size": item["size"],
            "sha256": item["sha256"],
        },
    )
    assert initialized.status_code == 201, initialized.text
    upload_id = initialized.json()["upload_id"]
    harness._seed_upload(upload_id, payload)
    completed = harness.client.post(f"/api/v1/uploads/{upload_id}/complete", json={})
    assert completed.status_code == 200, completed.text
    harness.drain()
    return upload_id


def test_publication_feature_flag_defaults_closed(harness: Any) -> None:
    from .conftest import pdb_bytes, pe_bytes

    workspace = harness.create_workspace("publication-disabled")
    pe = pe_bytes("11223344556677889900AABBCCDDEEFF1")
    pdb = pdb_bytes("11223344556677889900AABBCCDDEEFF1")
    response = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/build-publications",
        json=_publication(pe, pdb),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BUILD_PUBLICATIONS_DISABLED"


def test_identical_local_and_ci_publications_share_build_and_keep_provenance(
    harness: Any,
) -> None:
    from .conftest import pdb_bytes, pe_bytes

    _enable(harness)
    workspace = harness.create_workspace("publication-dedup")
    pe = pe_bytes("AABBCCDDEEFF001122334455667788991")
    pdb = pdb_bytes("AABBCCDDEEFF001122334455667788991")
    local_body = _publication(pe, pdb)

    first = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/build-publications",
        json=local_body,
    )
    assert first.status_code == 201, first.text
    first_payload = first.json()
    assert first_payload["status"] == "registered"
    assert first_payload["publication"]["git_worktree_state"] == "dirty"

    replay = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/build-publications",
        json=local_body,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["publication"]["id"] == first_payload["publication"]["id"]
    assert replay.json()["build_id"] == first_payload["build_id"]

    ci_body = _publication(
        pe,
        pdb,
        origin="ci",
        client_id="ci:gitlab:0123456789abcdef:release",
    )
    ci = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/build-publications",
        json=ci_body,
    )
    assert ci.status_code == 201, ci.text
    assert ci.json()["build_id"] == first_payload["build_id"]
    assert {item["origin"] for item in ci.json()["publications"]} == {"local", "ci"}

    changed = _publication(
        pe,
        pdb,
        client_id="local:0123456789abcdef:owned",
        role="owned",
    )
    changed_response = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/build-publications",
        json=changed,
    )
    assert changed_response.status_code == 422
    # Every Build Manifest must retain at least one entrypoint.
    assert changed_response.json()["error"]["code"] == "VALIDATION"


def test_expected_artifacts_verify_then_atomically_seal_build(harness: Any) -> None:
    from .conftest import pdb_bytes, pe_bytes

    _enable(harness)
    workspace = harness.create_workspace("publication-ready")
    debug_id = "00112233445566778899AABBCCDDEEFF1"
    pe = pe_bytes(debug_id)
    pdb = pdb_bytes(debug_id)
    body = _publication(pe, pdb)
    registered = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/build-publications",
        json=body,
    ).json()
    build_id = registered["build_id"]

    unexpected = harness.client.post(
        f"/api/v1/builds/{build_id}/artifacts/uploads:init",
        json={
            "file_kind": "pe",
            "filename": "other.exe",
            "size": len(pe),
            "sha256": _sha(pe),
        },
    )
    assert unexpected.status_code == 422
    assert unexpected.json()["error"]["code"] == "UNEXPECTED_ARTIFACT"

    _upload_expected(harness, build_id, body["artifacts"][0], pe)
    intermediate = harness.client.get(
        f"/api/v1/build-publications/{registered['publication']['id']}"
    ).json()
    assert intermediate["ready"] is False
    assert intermediate["status"] == "registered"

    _upload_expected(harness, build_id, body["artifacts"][1], pdb)
    ready = harness.client.get(f"/api/v1/builds/{build_id}/publication-status")
    assert ready.status_code == 200, ready.text
    payload = ready.json()
    assert payload["status"] == "ready", payload
    assert payload["ready"] is True
    assert payload["sealed_at"]
    assert {item["status"] for item in payload["expected_artifacts"]} == {"verified"}

    sealed_upload = harness.client.post(
        f"/api/v1/builds/{build_id}/artifacts/uploads:init",
        json={
            "file_kind": "pe",
            "filename": "app.exe",
            "size": len(pe),
            "sha256": _sha(pe),
        },
    )
    assert sealed_upload.status_code == 409
    assert sealed_upload.json()["error"]["code"] == "BUILD_SEALED"
    sealed_manifest = harness.client.put(
        f"/api/v1/builds/{build_id}/manifest", json=body["manifest"]
    )
    assert sealed_manifest.status_code == 409
    assert sealed_manifest.json()["error"]["code"] == "BUILD_SEALED"


def test_replaced_file_is_rejected_by_verified_bytes_and_never_seals(harness: Any) -> None:
    from .conftest import pdb_bytes, pe_bytes

    _enable(harness)
    workspace = harness.create_workspace("publication-replaced")
    debug_id = "FFEEDDCCBBAA998877665544332211001"
    pe = pe_bytes(debug_id)
    pdb = pdb_bytes(debug_id)
    body = _publication(pe, pdb)
    registered = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/build-publications",
        json=body,
    ).json()
    expected = body["artifacts"][0]
    initialized = harness.client.post(
        f"/api/v1/builds/{registered['build_id']}/artifacts/uploads:init",
        json={
            "file_kind": expected["kind"],
            "filename": expected["logical_name"],
            "size": expected["size"],
            "sha256": expected["sha256"],
        },
    ).json()
    replacement = bytearray(pe)
    replacement[-1] ^= 1
    harness._seed_upload(initialized["upload_id"], bytes(replacement))
    completed = harness.client.post(f"/api/v1/uploads/{initialized['upload_id']}/complete", json={})
    assert completed.status_code == 200
    harness.drain()
    upload = harness.client.get(f"/api/v1/uploads/{initialized['upload_id']}").json()
    assert upload["verification_status"] == "REJECTED"
    assert upload["rejection_reason"] == "sha256_mismatch"

    status = harness.client.get(
        f"/api/v1/build-publications/{registered['publication']['id']}"
    ).json()
    assert status["status"] == "rejected"
    assert status["ready"] is False
    assert status["sealed_at"] is None
    assert status["rejected_artifacts"][0]["rejection_reason"] == "sha256_mismatch"


def test_workspace_roles_preserve_both_sealed_publications(harness: Any) -> None:
    from crashcap_api.models import Artifact, Build, BuildModule, WorkspaceModuleRole

    from .conftest import pdb_bytes, pe_bytes

    _enable(harness)
    harness.app.state.settings.workspace_module_roles_enabled = True
    debug_id = "00112233445566778899AABBCCDDEEFF1"
    pe, pdb = pe_bytes(debug_id), pdb_bytes(debug_id)
    consumers = []
    for name in ("sealed-owned", "sealed-dependency"):
        workspace = harness.create_workspace(name)
        body = _publication(pe, pdb)
        response = harness.client.post(
            f"/api/v1/workspaces/{workspace['id']}/build-publications", json=body
        )
        assert response.status_code == 201, response.text
        build_id = response.json()["build_id"]
        for item, content in zip(body["artifacts"], (pe, pdb), strict=True):
            _upload_expected(harness, build_id, item, content)
        status = harness.client.get(f"/api/v1/builds/{build_id}/publication-status").json()
        assert status["ready"] and status["sealed_at"]
        consumers.append((workspace["id"], build_id, status))
    build_ids = [row[1] for row in consumers]
    assert len(set(build_ids)) == 2

    def historical_state():
        with harness.app.state.database.sessions() as session:
            rows = {}
            for model in (Build, BuildModule, Artifact):
                table = model.__table__
                owner = table.c.id if model is Build else table.c.build_id
                rows[table.name] = [
                    dict(row)
                    for row in session.execute(
                        table.select().where(owner.in_(build_ids)).order_by(table.c.id)
                    ).mappings()
                ]
            manifests = {
                row["id"]: b"".join(harness.app.state.store.stream(row["manifest_object_key"]))
                for row in rows[Build.__tablename__]
            }
            return rows, manifests

    before = historical_state()
    with harness.app.state.database.sessions() as session:
        artifact = session.query(Artifact).filter_by(build_id=build_ids[0], kind="pe").one()
        identity = {
            "code_id": artifact.code_id,
            "debug_id": artifact.debug_id,
            "architecture": "x86_64",
        }
    for (workspace_id, _, _), role in zip(consumers, ("owned", "dependency"), strict=True):
        response = harness.client.post(
            f"/api/v2/workspaces/{workspace_id}/module-roles",
            json={"identity": identity, "role": role},
        )
        assert response.status_code == 201, response.text
        harness.drain()
        assert historical_state() == before
    with harness.app.state.database.sessions() as session:
        assert {row.workspace_id: row.role for row in session.query(WorkspaceModuleRole).all()} == {
            consumers[0][0]: "owned",
            consumers[1][0]: "dependency",
        }
    for _, build_id, status in consumers:
        assert harness.client.get(f"/api/v1/builds/{build_id}/publication-status").json() == status


def test_fingerprint_is_order_stable_and_changes_with_manifest_role() -> None:
    manifest = _manifest()
    artifacts = [
        {"kind": "pe", "logical_name": "app.exe", "size": 10, "sha256": "a" * 64},
        {"kind": "pdb", "logical_name": "app.pdb", "size": 20, "sha256": "b" * 64},
    ]
    first = canonical_fingerprint(manifest, artifacts)
    assert first == canonical_fingerprint(manifest, list(reversed(artifacts)))
    changed = _manifest(role="owned")
    assert first != canonical_fingerprint(changed, artifacts)


def test_publication_rejects_non_pe_pdb_module_names_offline_from_worker(harness: Any) -> None:
    from .conftest import pdb_bytes, pe_bytes

    _enable(harness)
    workspace = harness.create_workspace("publication-file-extensions")
    pe = pe_bytes("11223344556677889900AABBCCDDEEFF1")
    pdb = pdb_bytes("11223344556677889900AABBCCDDEEFF1")
    body = _publication(pe, pdb)
    body["manifest"]["modules"][0]["code_file"] = "app.bin"
    body["manifest"]["modules"][0]["debug_file"] = "app.dbg"
    for artifact in body["artifacts"]:
        artifact["module_code_file"] = "app.bin"
        artifact["logical_name"] = "app.bin" if artifact["kind"] == "pe" else "app.dbg"

    response = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/build-publications",
        json=body,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSUPPORTED_ARTIFACT_PROFILE"
