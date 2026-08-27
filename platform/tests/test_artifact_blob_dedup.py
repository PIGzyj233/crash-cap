from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from crashcap_api.models import (
    Artifact,
    ArtifactBlob,
    ArtifactBlobPair,
    ArtifactBlobUploadClaim,
    OperationLog,
    Workspace,
)
from sqlalchemy import func, select


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _publication(
    *,
    version: str,
    client_id: str,
    modules: list[tuple[str, str, str, bytes, bytes]],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "origin": "local",
        "client_publication_id": client_id,
        "client_version": "crashcap/1.1.0",
        "git": {"revision": "0123456789abcdef", "worktree_state": "clean"},
        "manifest": {
            "schema_version": "1.0",
            "product": "Artifact Blob Test",
            "version": version,
            "architecture": "x86_64",
            "compiler": "msvc",
            "modules": [
                {
                    "code_file": code_file,
                    "debug_file": debug_file,
                    "role": role,
                }
                for code_file, debug_file, role, _pe, _pdb in modules
            ],
        },
        "artifacts": [
            artifact
            for code_file, debug_file, _role, pe, pdb in modules
            for artifact in (
                {
                    "module_code_file": code_file,
                    "kind": "pe",
                    "logical_name": code_file,
                    "size": len(pe),
                    "sha256": _sha(pe),
                },
                {
                    "module_code_file": code_file,
                    "kind": "pdb",
                    "logical_name": debug_file,
                    "size": len(pdb),
                    "sha256": _sha(pdb),
                },
            )
        ],
    }


def _enable_active(harness: Any) -> None:
    harness.settings.build_publications_enabled = True
    harness.settings.artifact_blob_dedup_mode = "active"


def _register(harness: Any, workspace_id: str, body: dict[str, Any]) -> dict[str, Any]:
    response = harness.client.post(
        f"/api/v1/workspaces/{workspace_id}/build-publications",
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _deliver_upload(
    harness: Any, build_id: str, expected: dict[str, Any], payload: bytes
) -> dict[str, Any]:
    initialized = harness.client.post(
        f"/api/v1/builds/{build_id}/artifacts/deliveries:init",
        json={
            "file_kind": expected["kind"],
            "filename": expected["logical_name"],
            "size": expected["size"],
            "sha256": expected["sha256"],
        },
    )
    assert initialized.status_code == 201, initialized.text
    response = initialized.json()
    assert response["disposition"] == "upload", response
    harness._seed_upload(response["upload_id"], payload)
    complete = harness.client.post(f"/api/v1/uploads/{response['upload_id']}/complete", json={})
    assert complete.status_code == 200, complete.text
    harness.drain()
    terminal = harness.client.get(f"/api/v1/uploads/{response['upload_id']}")
    assert terminal.status_code == 200, terminal.text
    assert terminal.json()["verification_status"] == "ACCEPTED", terminal.text
    return terminal.json()


def _artifact(body: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in body["artifacts"] if item["logical_name"] == name)


def test_delivery_capability_is_advertised_only_in_active_mode(harness: Any) -> None:
    producers = harness.client.get("/api/v1/artifact-producers")
    assert producers.status_code == 200
    assert all(item["artifact_delivery_contracts"] == [] for item in producers.json())
    harness.settings.artifact_blob_dedup_mode = "shadow"
    assert all(
        item["artifact_delivery_contracts"] == []
        for item in harness.client.get("/api/v1/artifact-producers").json()
    )
    harness.settings.artifact_blob_dedup_mode = "active"
    assert all(
        item["artifact_delivery_contracts"]
        == ["artifact-delivery-v1", "artifact-delivery-v2"]
        for item in harness.client.get("/api/v1/artifact-producers").json()
    )


def test_content_build_off_mode_advances_inventory_only_when_it_first_seals(
    harness: Any,
) -> None:
    from .conftest import pdb_bytes, pe_bytes

    harness.settings.build_publications_enabled = True
    harness.settings.artifact_blob_dedup_mode = "off"
    workspace = harness.create_workspace("artifact-blob-off-inventory")
    debug_id = "101010101010101010101010101010101"
    pe, pdb = pe_bytes(debug_id), pdb_bytes(debug_id)
    body = _publication(
        version="1.0.0",
        client_id="local:off-inventory",
        modules=[("off.exe", "off.pdb", "entrypoint", pe, pdb)],
    )
    registered = _register(harness, workspace["id"], body)
    for expected, payload in zip(body["artifacts"], (pe, pdb), strict=True):
        initialized = harness.client.post(
            f"/api/v1/builds/{registered['build_id']}/artifacts/uploads:init",
            json={
                "file_kind": expected["kind"],
                "filename": expected["logical_name"],
                "size": expected["size"],
                "sha256": expected["sha256"],
            },
        ).json()
        harness._seed_upload(initialized["upload_id"], payload)
        harness.client.post(f"/api/v1/uploads/{initialized['upload_id']}/complete", json={})
        harness.drain()
    status = harness.client.get(
        f"/api/v1/builds/{registered['build_id']}/publication-status"
    ).json()
    assert status["ready"] is True
    with harness.app.state.database.sessions() as session:
        row = session.get(Workspace, workspace["id"])
        assert row is not None and row.symbol_inventory_version == 1


def test_four_file_build_reuses_unchanged_dependency_and_seals(harness: Any) -> None:
    from .conftest import pdb_bytes, pe_bytes

    _enable_active(harness)
    workspace = harness.create_workspace("artifact-blob-four-file")
    main_a_id = "111111111111111111111111111111111"
    main_b_id = "222222222222222222222222222222221"
    xrtc_id = "333333333333333333333333333333331"
    main_a = (
        "lightstreamer.exe",
        "lightstreamer.pdb",
        "entrypoint",
        pe_bytes(main_a_id),
        pdb_bytes(main_a_id),
    )
    xrtc = (
        "xrtc_router.dll",
        "xrtc_router.dll.pdb",
        "dependency",
        pe_bytes(xrtc_id),
        pdb_bytes(xrtc_id),
    )
    body_a = _publication(version="1.0.0", client_id="local:build-a", modules=[main_a, xrtc])
    registered_a = _register(harness, workspace["id"], body_a)
    assert len(registered_a["expected_artifacts"]) == 4
    payloads_a = {
        "lightstreamer.exe": main_a[3],
        "lightstreamer.pdb": main_a[4],
        "xrtc_router.dll": xrtc[3],
        "xrtc_router.dll.pdb": xrtc[4],
    }
    for item in body_a["artifacts"]:
        receipt = _deliver_upload(
            harness, registered_a["build_id"], item, payloads_a[item["logical_name"]]
        )
        assert set(receipt) <= {
            "upload_id",
            "status",
            "verification_status",
            "sha256",
            "duplicate",
            "artifact_blob_id",
            "delivery",
            "rejection_reason",
        }

    ready_a = harness.client.get(
        f"/api/v1/builds/{registered_a['build_id']}/publication-status"
    ).json()
    assert ready_a["ready"] is True
    assert {item["delivery"] for item in ready_a["expected_artifacts"]} == {"uploaded"}

    main_b = (
        "lightstreamer.exe",
        "lightstreamer.pdb",
        "entrypoint",
        pe_bytes(main_b_id),
        pdb_bytes(main_b_id),
    )
    body_b = _publication(version="1.0.1", client_id="local:build-b", modules=[main_b, xrtc])
    registered_b = _register(harness, workspace["id"], body_b)
    assert len(registered_b["expected_artifacts"]) == 4
    xrtc_rows = [
        item
        for item in registered_b["expected_artifacts"]
        if item["logical_name"].startswith("xrtc_router")
    ]
    assert len(xrtc_rows) == 2
    assert {item["status"] for item in xrtc_rows} == {"verified"}
    assert {item["delivery"] for item in xrtc_rows} == {"reused"}
    assert all(item["artifact_blob_id"].startswith("abl_") for item in xrtc_rows)

    for item, payload in (
        (_artifact(body_b, "lightstreamer.exe"), main_b[3]),
        (_artifact(body_b, "lightstreamer.pdb"), main_b[4]),
    ):
        _deliver_upload(harness, registered_b["build_id"], item, payload)
    ready_b = harness.client.get(
        f"/api/v1/builds/{registered_b['build_id']}/publication-status"
    ).json()
    assert ready_b["ready"] is True
    assert len(ready_b["expected_artifacts"]) == 4
    deliveries = {item["logical_name"]: item["delivery"] for item in ready_b["expected_artifacts"]}
    assert deliveries == {
        "lightstreamer.exe": "uploaded",
        "lightstreamer.pdb": "uploaded",
        "xrtc_router.dll": "reused",
        "xrtc_router.dll.pdb": "reused",
    }

    with harness.app.state.database.sessions() as session:
        workspace_row = session.get(Workspace, workspace["id"])
        assert workspace_row is not None
        assert workspace_row.symbol_inventory_version == 2
        for payload in (xrtc[3], xrtc[4]):
            digest = _sha(payload)
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ArtifactBlob)
                    .where(
                        ArtifactBlob.workspace_id == workspace["id"],
                        ArtifactBlob.sha256 == digest,
                    )
                )
                == 1
            )
        build_b_artifacts = session.scalars(
            select(Artifact).where(Artifact.build_id == registered_b["build_id"])
        ).all()
        assert len(build_b_artifacts) == 4
        assert sum(row.materialization_source == "blob_reuse" for row in build_b_artifacts) == 2

        changed_blob = session.scalar(
            select(ArtifactBlob).where(
                ArtifactBlob.workspace_id == workspace["id"],
                ArtifactBlob.sha256 == _sha(main_b[3]),
            )
        )
        assert changed_blob is not None
        changed_blob_key = changed_blob.object_key

    # A lost canonical object is an integrity/recovery incident. It must not
    # turn a sealed Build back into a mutable replacement-upload target.
    harness.app.state.store.delete(changed_blob_key)
    sealed_retry = harness.client.post(
        f"/api/v1/builds/{registered_b['build_id']}/artifacts/deliveries:init",
        json={
            "file_kind": "pe",
            "filename": "lightstreamer.exe",
            "size": len(main_b[3]),
            "sha256": _sha(main_b[3]),
        },
    )
    assert sealed_retry.status_code == 409
    assert sealed_retry.json()["error"]["code"] == "BUILD_SEALED"
    with harness.app.state.database.sessions() as session:
        changed_blob = session.scalar(
            select(ArtifactBlob).where(
                ArtifactBlob.workspace_id == workspace["id"],
                ArtifactBlob.sha256 == _sha(main_b[3]),
            )
        )
        assert changed_blob is not None and changed_blob.verification_status == "missing"


def test_first_transfer_is_single_flight_then_materializes_both_builds(harness: Any) -> None:
    from .conftest import pdb_bytes, pe_bytes

    _enable_active(harness)
    workspace = harness.create_workspace("artifact-blob-race")
    debug_id = "444444444444444444444444444444441"
    pe, pdb = pe_bytes(debug_id), pdb_bytes(debug_id)
    first_body = _publication(
        version="1.0.0",
        client_id="local:race-a",
        modules=[("race.exe", "race.pdb", "entrypoint", pe, pdb)],
    )
    second_body = _publication(
        version="1.0.1",
        client_id="local:race-b",
        modules=[("race.exe", "race.pdb", "entrypoint", pe, pdb)],
    )
    first = _register(harness, workspace["id"], first_body)
    second = _register(harness, workspace["id"], second_body)
    expected = _artifact(first_body, "race.exe")
    request = {
        "file_kind": "pe",
        "filename": "race.exe",
        "size": len(pe),
        "sha256": _sha(pe),
    }
    owner = harness.client.post(
        f"/api/v1/builds/{first['build_id']}/artifacts/deliveries:init", json=request
    )
    waiter = harness.client.post(
        f"/api/v1/builds/{second['build_id']}/artifacts/deliveries:init", json=request
    )
    assert owner.json()["disposition"] == "upload"
    assert waiter.json()["disposition"] == "wait"
    assert set(waiter.json()) == {
        "disposition",
        "retry_after_seconds",
        "lease_expires_at",
    }

    harness._seed_upload(owner.json()["upload_id"], pe)
    assert harness.client.post(
        f"/api/v1/uploads/{owner.json()['upload_id']}/complete", json={}
    ).status_code == 200
    harness.drain()
    reused = harness.client.post(
        f"/api/v1/builds/{second['build_id']}/artifacts/deliveries:init", json=request
    )
    assert reused.status_code == 201, reused.text
    assert reused.json()["disposition"] == "reused"
    assert set(reused.json()) == {
        "disposition",
        "artifact_blob_id",
        "artifact_id",
        "delivery",
    }
    with harness.app.state.database.sessions() as session:
        bindings = session.scalars(
            select(Artifact).where(
                Artifact.build_id.in_([first["build_id"], second["build_id"]]),
                Artifact.kind == "pe",
                Artifact.sha256 == expected["sha256"],
            )
        ).all()
        assert len(bindings) == 2
        assert len({row.artifact_blob_id for row in bindings}) == 1


def test_claim_expiry_takeover_and_wrong_bytes_release_claim(harness: Any) -> None:
    from .conftest import pdb_bytes, pe_bytes

    _enable_active(harness)
    workspace = harness.create_workspace("artifact-blob-claim")
    debug_id = "555555555555555555555555555555551"
    pe, pdb = pe_bytes(debug_id), pdb_bytes(debug_id)
    body = _publication(
        version="1.0.0",
        client_id="local:claim",
        modules=[("claim.exe", "claim.pdb", "entrypoint", pe, pdb)],
    )
    registered = _register(harness, workspace["id"], body)
    expected = _artifact(body, "claim.exe")
    request = {
        "file_kind": expected["kind"],
        "filename": expected["logical_name"],
        "size": expected["size"],
        "sha256": expected["sha256"],
    }
    first = harness.client.post(
        f"/api/v1/builds/{registered['build_id']}/artifacts/deliveries:init", json=request
    ).json()
    with harness.app.state.database.sessions() as session:
        claim = session.scalar(
            select(ArtifactBlobUploadClaim).where(
                ArtifactBlobUploadClaim.workspace_id == workspace["id"],
                ArtifactBlobUploadClaim.sha256 == expected["sha256"],
            )
        )
        assert claim is not None
        claim.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    takeover = harness.client.post(
        f"/api/v1/builds/{registered['build_id']}/artifacts/deliveries:init", json=request
    ).json()
    assert takeover["disposition"] == "upload"
    assert takeover["upload_id"] != first["upload_id"]

    wrong = bytearray(pe)
    wrong[-1] ^= 1
    harness._seed_upload(takeover["upload_id"], bytes(wrong))
    completed = harness.client.post(f"/api/v1/uploads/{takeover['upload_id']}/complete", json={})
    assert completed.status_code == 200
    harness.drain()
    terminal = harness.client.get(f"/api/v1/uploads/{takeover['upload_id']}").json()
    assert terminal["verification_status"] == "REJECTED"
    assert terminal["rejection_reason"] == "sha256_mismatch"
    with harness.app.state.database.sessions() as session:
        assert session.get(
            ArtifactBlobUploadClaim,
            {"workspace_id": workspace["id"], "sha256": expected["sha256"]},
        ) is None
        assert session.scalar(
            select(ArtifactBlob).where(
                ArtifactBlob.workspace_id == workspace["id"],
                ArtifactBlob.sha256 == expected["sha256"],
            )
        ) is None


def test_fastlink_and_pair_mismatch_do_not_poison_valid_blob(harness: Any) -> None:
    from .conftest import pdb_bytes, pe_bytes

    _enable_active(harness)
    workspace = harness.create_workspace("artifact-blob-pair-isolation")
    first_id = "666666666666666666666666666666661"
    second_id = "777777777777777777777777777777771"
    pe_first = pe_bytes(first_id)
    shared_pdb = pdb_bytes(second_id)
    mismatch_body = _publication(
        version="1.0.0",
        client_id="local:mismatch",
        modules=[("mismatch.exe", "shared.pdb", "entrypoint", pe_first, shared_pdb)],
    )
    mismatch = _register(harness, workspace["id"], mismatch_body)
    _deliver_upload(harness, mismatch["build_id"], mismatch_body["artifacts"][0], pe_first)
    _deliver_upload(harness, mismatch["build_id"], mismatch_body["artifacts"][1], shared_pdb)
    with harness.app.state.database.sessions() as session:
        pairs = session.scalars(select(ArtifactBlobPair)).all()
        artifact_states = session.execute(
            select(Artifact.kind, Artifact.verification_status).where(
                Artifact.build_id == mismatch["build_id"]
            )
        ).all()
        assert len(pairs) == 1, artifact_states
        assert pairs[0].state == "rejected", artifact_states
        assert {state for _kind, state in artifact_states} == {
            "pe_mismatch",
            "pdb_mismatch",
        }, pairs[0].state
    mismatch_status = harness.client.get(
        f"/api/v1/builds/{mismatch['build_id']}/publication-status"
    ).json()
    assert mismatch_status["ready"] is False
    assert {item["status"] for item in mismatch_status["expected_artifacts"]} == {
        "rejected"
    }

    matching_pe = pe_bytes(second_id)
    match_body = _publication(
        version="1.0.1",
        client_id="local:matching",
        modules=[("matching.exe", "shared.pdb", "entrypoint", matching_pe, shared_pdb)],
    )
    matching = _register(harness, workspace["id"], match_body)
    shared = _artifact(match_body, "shared.pdb")
    shared_row = next(
        item for item in matching["expected_artifacts"] if item["logical_name"] == "shared.pdb"
    )
    assert shared_row["delivery"] == "reused"
    _deliver_upload(
        harness,
        matching["build_id"],
        _artifact(match_body, "matching.exe"),
        matching_pe,
    )
    ready = harness.client.get(
        f"/api/v1/builds/{matching['build_id']}/publication-status"
    ).json()
    assert ready["ready"] is True
    assert next(item for item in ready["expected_artifacts"] if item["sha256"] == shared["sha256"])[
        "status"
    ] == "verified"

    fastlink_body = _publication(
        version="1.0.2",
        client_id="local:fastlink",
        modules=[
            (
                "fastlink.exe",
                "fastlink.pdb",
                "entrypoint",
                pe_bytes(first_id),
                pdb_bytes(first_id, fastlink=True),
            )
        ],
    )
    fastlink = _register(harness, workspace["id"], fastlink_body)
    fastlink_expected = _artifact(fastlink_body, "fastlink.pdb")
    terminal = _deliver_upload(
        harness,
        fastlink["build_id"],
        fastlink_expected,
        pdb_bytes(first_id, fastlink=True),
    )
    # Upload bytes passed hash verification, then Artifact identification rejected FASTLINK.
    assert terminal["verification_status"] == "ACCEPTED"
    status = harness.client.get(
        f"/api/v1/builds/{fastlink['build_id']}/publication-status"
    ).json()
    rejected = next(
        item for item in status["expected_artifacts"] if item["logical_name"] == "fastlink.pdb"
    )
    assert rejected["status"] == "rejected"
    assert rejected["rejection_reason"] == "rejected_fastlink"
    with harness.app.state.database.sessions() as session:
        assert session.scalar(
            select(ArtifactBlob).where(
                ArtifactBlob.workspace_id == workspace["id"],
                ArtifactBlob.sha256 == fastlink_expected["sha256"],
            )
        ) is None


def test_workspace_isolation_and_canonical_loss_disable_reuse(harness: Any) -> None:
    from .conftest import pdb_bytes, pe_bytes

    _enable_active(harness)
    first_workspace = harness.create_workspace("artifact-blob-workspace-a")
    second_workspace = harness.create_workspace("artifact-blob-workspace-b")
    debug_id = "888888888888888888888888888888881"
    pe, pdb = pe_bytes(debug_id), pdb_bytes(debug_id)
    bodies = [
        _publication(
            version="1.0.0",
            client_id=f"local:workspace-{suffix}",
            modules=[("isolated.exe", "isolated.pdb", "entrypoint", pe, pdb)],
        )
        for suffix in ("a", "b")
    ]
    first = _register(harness, first_workspace["id"], bodies[0])
    _deliver_upload(harness, first["build_id"], bodies[0]["artifacts"][0], pe)
    second = _register(harness, second_workspace["id"], bodies[1])
    second_init = harness.client.post(
        f"/api/v1/builds/{second['build_id']}/artifacts/deliveries:init",
        json={
            "file_kind": "pe",
            "filename": "isolated.exe",
            "size": len(pe),
            "sha256": _sha(pe),
        },
    )
    assert second_init.json()["disposition"] == "upload"

    with harness.app.state.database.sessions() as session:
        blob = session.scalar(
            select(ArtifactBlob).where(
                ArtifactBlob.workspace_id == first_workspace["id"],
                ArtifactBlob.sha256 == _sha(pe),
            )
        )
        assert blob is not None
        canonical_key = blob.object_key
    harness.app.state.store.delete(canonical_key)
    third_body = _publication(
        version="1.0.1",
        client_id="local:workspace-a-loss",
        modules=[("isolated.exe", "isolated.pdb", "entrypoint", pe, pdb)],
    )
    third = _register(harness, first_workspace["id"], third_body)
    lost = harness.client.post(
        f"/api/v1/builds/{third['build_id']}/artifacts/deliveries:init",
        json={
            "file_kind": "pe",
            "filename": "isolated.exe",
            "size": len(pe),
            "sha256": _sha(pe),
        },
    )
    assert lost.json()["disposition"] == "upload"
    with harness.app.state.database.sessions() as session:
        blob = session.scalar(
            select(ArtifactBlob).where(
                ArtifactBlob.workspace_id == first_workspace["id"],
                ArtifactBlob.sha256 == _sha(pe),
            )
        )
        assert blob is not None and blob.verification_status == "missing"


def test_shadow_mode_populates_blob_but_never_skips_upload(harness: Any) -> None:
    from .conftest import pdb_bytes, pe_bytes

    harness.settings.build_publications_enabled = True
    harness.settings.artifact_blob_dedup_mode = "shadow"
    workspace = harness.create_workspace("artifact-blob-shadow")
    debug_id = "ABCDEFABCDEFABCDEFABCDEFABCDEFAB1"
    pe, pdb = pe_bytes(debug_id), pdb_bytes(debug_id)
    first_body = _publication(
        version="1.0.0",
        client_id="local:shadow-a",
        modules=[("shadow.exe", "shadow.pdb", "entrypoint", pe, pdb)],
    )
    first = _register(harness, workspace["id"], first_body)
    for item, payload in zip(first_body["artifacts"], (pe, pdb), strict=True):
        initialized = harness.client.post(
            f"/api/v1/builds/{first['build_id']}/artifacts/uploads:init",
            json={
                "file_kind": item["kind"],
                "filename": item["logical_name"],
                "size": item["size"],
                "sha256": item["sha256"],
            },
        ).json()
        harness._seed_upload(initialized["upload_id"], payload)
        harness.client.post(f"/api/v1/uploads/{initialized['upload_id']}/complete", json={})
        harness.drain()
    second_body = _publication(
        version="1.0.1",
        client_id="local:shadow-b",
        modules=[("shadow.exe", "shadow.pdb", "entrypoint", pe, pdb)],
    )
    second = _register(harness, workspace["id"], second_body)
    assert {item["status"] for item in second["expected_artifacts"]} == {"missing"}
    disabled = harness.client.post(
        f"/api/v1/builds/{second['build_id']}/artifacts/deliveries:init",
        json={
            "file_kind": "pe",
            "filename": "shadow.exe",
            "size": len(pe),
            "sha256": _sha(pe),
        },
    )
    assert disabled.status_code == 404
    assert disabled.json()["error"]["code"] == "ARTIFACT_DELIVERY_DISABLED"
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ArtifactBlob)) == 2
        assert session.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.build_id == second["build_id"])
        ) == 0


def test_old_upload_route_converges_and_responses_logs_are_safe(harness: Any) -> None:
    from .conftest import pdb_bytes, pe_bytes

    _enable_active(harness)
    workspace = harness.create_workspace("artifact-blob-old-client")
    debug_id = "999999999999999999999999999999991"
    pe, pdb = pe_bytes(debug_id), pdb_bytes(debug_id)
    body = _publication(
        version="1.0.0",
        client_id="local:old-client",
        modules=[("legacy-client.exe", "legacy-client.pdb", "entrypoint", pe, pdb)],
    )
    registered = _register(harness, workspace["id"], body)
    expected = _artifact(body, "legacy-client.exe")
    old = harness.client.post(
        f"/api/v1/builds/{registered['build_id']}/artifacts/uploads:init",
        json={
            "file_kind": expected["kind"],
            "filename": expected["logical_name"],
            "size": expected["size"],
            "sha256": expected["sha256"],
        },
    )
    assert old.status_code == 201
    harness._seed_upload(old.json()["upload_id"], pe)
    harness.client.post(f"/api/v1/uploads/{old.json()['upload_id']}/complete", json={})
    harness.drain()
    status = harness.client.get(
        f"/api/v1/builds/{registered['build_id']}/publication-status"
    ).json()
    row = next(item for item in status["expected_artifacts"] if item["kind"] == "pe")
    assert row["artifact_blob_id"].startswith("abl_")
    assert row["delivery"] == "uploaded"
    encoded = str(status).casefold()
    assert "object_key" not in encoded
    assert "presigned" not in encoded
    assert "credential" not in encoded
    with harness.app.state.database.sessions() as session:
        logs = session.scalars(
            select(OperationLog).where(OperationLog.workspace_id == workspace["id"])
        ).all()
        assert logs
        rendered = str([row.details for row in logs]).casefold()
        assert "presigned" not in rendered
        assert "credential" not in rendered
        assert "artifact-blobs/" not in rendered
        assert session.scalar(select(func.count()).select_from(ArtifactBlobPair)) == 0
