from __future__ import annotations

from crashcap_api.models import ArtifactBlob, Workspace
from crashcap_api.symbol_source import create_symbol_source_app
from fastapi.testclient import TestClient
from sqlalchemy import select

from .conftest import Phase1Harness
from .test_artifact_payload_rollout import _publish_one_pair


def test_internal_symbol_source_materializes_verified_workspace_scoped_payload(
    harness: Phase1Harness,
) -> None:
    registered, pe, pdb = _publish_one_pair(
        harness,
        workspace_name="http-symbol-source",
        compression_mode="active",
    )
    workspace_id = registered["publication"]["workspace_id"]
    with harness.app.state.database.sessions() as session:
        workspace = session.get(Workspace, workspace_id)
        assert workspace is not None
        inventory = workspace.symbol_inventory_version
        blobs = session.scalars(
            select(ArtifactBlob)
            .where(ArtifactBlob.workspace_id == workspace_id)
            .order_by(ArtifactBlob.kind)
        ).all()

    source_app = create_symbol_source_app(
        harness.settings,
        database=harness.app.state.database,
        store=harness.app.state.store,
    )
    with TestClient(source_app) as client:
        for blob in blobs:
            assert blob.debug_id is not None
            debug_id = blob.debug_id.lower()
            leaf = "executable" if blob.kind == "pe" else "debuginfo"
            path = (
                f"/v1/workspaces/{workspace_id}/inventories/{inventory}/"
                f"{debug_id[:2]}/{debug_id[2:]}/{leaf}"
            )
            head = client.head(path)
            assert head.status_code == 200
            assert int(head.headers["content-length"]) == blob.size
            response = client.get(path)
            assert response.status_code == 200
            assert response.content == (pe if blob.kind == "pe" else pdb)
            assert blob.payload_object_key not in response.text

        with harness.app.state.database.sessions() as session:
            workspace = session.get(Workspace, workspace_id)
            assert workspace is not None
            workspace.symbol_inventory_version += 1
            session.commit()
        # An unrelated later publication must not invalidate an in-flight Run's
        # already-captured source inventory.
        assert client.get(path).status_code == 200


def test_internal_symbol_source_rejects_wrong_scope_inventory_and_corruption(
    harness: Phase1Harness,
) -> None:
    registered, _pe, _pdb = _publish_one_pair(
        harness,
        workspace_name="http-symbol-source-fault",
        compression_mode="active",
    )
    workspace_id = registered["publication"]["workspace_id"]
    other = harness.create_workspace("http-symbol-source-other")
    with harness.app.state.database.sessions() as session:
        workspace = session.get(Workspace, workspace_id)
        assert workspace is not None
        inventory = workspace.symbol_inventory_version
        blob = session.scalar(
            select(ArtifactBlob).where(
                ArtifactBlob.workspace_id == workspace_id,
                ArtifactBlob.kind == "pdb",
            )
        )
        assert blob is not None and blob.debug_id is not None
    debug_id = blob.debug_id.lower()
    suffix = f"{debug_id[:2]}/{debug_id[2:]}/debuginfo"
    source_app = create_symbol_source_app(
        harness.settings,
        database=harness.app.state.database,
        store=harness.app.state.store,
    )
    with TestClient(source_app) as client:
        assert client.get(f"/v1/workspaces/{other['id']}/inventories/0/{suffix}").status_code == 404
        assert (
            client.get(
                f"/v1/workspaces/{workspace_id}/inventories/{inventory + 1}/{suffix}"
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/v1/workspaces/{workspace_id}/inventories/{inventory}/../{suffix}"
            ).status_code
            == 404
        )
        harness.app.state.store.put_bytes(
            blob.payload_object_key,
            b"corrupt".ljust(blob.payload_size, b"!"),
            "application/octet-stream",
        )
        corrupted = client.get(f"/v1/workspaces/{workspace_id}/inventories/{inventory}/{suffix}")
        assert corrupted.status_code == 503
        assert corrupted.json()["error"]["code"] == "SYMBOL_PAYLOAD_UNAVAILABLE"
