from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from crashcap_api.response_contracts import CANONICAL_COMPONENT
from crashcap_api.response_models import (
    BuildResponse,
    OccurrenceResponse,
    UploadCompletionResponse,
    UploadInitResponse,
    WorkspaceResponse,
)
from pydantic import BaseModel, ConfigDict

from .conftest import Phase1Harness, dump_bytes, pdb_bytes, pe_bytes

DEBUG_ID = "d" * 32 + "1"


def _assert_json_response(
    response: Any,
    status: int,
    keys: set[str] | None = None,
    *,
    request_id: str | None = None,
) -> Any:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    if request_id is not None:
        assert response.headers["x-request-id"] == request_id
    payload = response.json()
    if keys is not None:
        assert set(payload) == keys
    return payload


def _assert_model_round_trip(model: type[BaseModel], payload: Any) -> None:
    validated = model.model_validate(payload)
    assert validated.model_dump(mode="json", exclude_unset=True) == payload


def test_three_response_waves_preserve_wire_status_headers_and_payloads(
    harness: Phase1Harness,
) -> None:
    request_id = "req_rep_baseline"
    created = harness.client.post(
        "/api/v1/workspaces",
        headers={"X-Request-ID": request_id},
        json={"name": "rep-baseline", "display_name": "REP baseline"},
    )
    workspace = _assert_json_response(
        created,
        201,
        {
            "id",
            "name",
            "display_name",
            "platform",
            "default_architecture",
            "retention_days",
            "symbol_inventory_version",
            "in_app_rule_version",
            "in_app_rules",
            "created_at",
        },
        request_id=request_id,
    )
    _assert_model_round_trip(WorkspaceResponse, workspace)

    build = harness.create_build(workspace["id"], "5.0.0")
    harness.client.put(
        f"/api/v1/builds/{build['id']}/manifest",
        json={
            "schema_version": "1.0",
            "product": "REP Gate",
            "version": "5.0.0",
            "architecture": "x86_64",
            "modules": [{"code_file": "app.exe", "debug_file": "app.pdb", "role": "entrypoint"}],
        },
    )
    presigned = _assert_json_response(
        harness.client.post(
            f"/api/v1/builds/{build['id']}/artifacts/uploads:init",
            json={"file_kind": "pe", "filename": "compat.exe", "size": 16},
        ),
        201,
        {"upload_id", "method", "url", "headers", "expires_in"},
    )
    assert presigned["method"] == "PUT"
    assert presigned["expires_in"] > 0
    harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(DEBUG_ID))
    harness.upload_artifact(build["id"], "pdb", "app.pdb", pdb_bytes(DEBUG_ID))
    build_payload = _assert_json_response(
        harness.client.get(f"/api/v1/builds/{build['id']}"),
        200,
        {
            "id",
            "workspace_id",
            "version",
            "build_number",
            "commit_sha",
            "channel",
            "architecture",
            "toolchain",
            "producer",
            "producer_build_id",
            "manifest_object_key",
            "manifest_schema_version",
            "source_bundle_config",
            "identity_mode",
            "fingerprint_version",
            "content_fingerprint",
            "sealed_at",
            "created_at",
            "modules",
            "artifacts",
            "groups",
        },
    )
    _assert_model_round_trip(BuildResponse, build_payload)
    first_page = _assert_json_response(
        harness.client.get(f"/api/v1/workspaces/{workspace['id']}/builds", params={"limit": 1}),
        200,
    )
    assert [item["id"] for item in first_page] == [build["id"]]
    next_page = _assert_json_response(
        harness.client.get(
            f"/api/v1/workspaces/{workspace['id']}/builds",
            params={"limit": 1, "cursor": build["id"]},
        ),
        200,
    )
    assert next_page == []

    producer_rows = _assert_json_response(harness.client.get("/api/v1/ci/producers"), 200)
    assert {row["producer"] for row in producer_rows} == {"msvc", "clang-cl", "crashpad"}
    ci_status = _assert_json_response(
        harness.client.get(f"/api/v1/builds/{build['id']}/ci-status"), 200
    )
    assert ci_status["ready"] is True

    upload = harness.upload_dump(workspace["id"], dump_bytes(501), reported_build_id=build["id"])
    _assert_model_round_trip(UploadCompletionResponse, upload)
    occurrence_id = upload["occurrence_id"]
    occurrence = _assert_json_response(
        harness.client.get(f"/api/v1/occurrences/{occurrence_id}"),
        200,
        {
            "id",
            "workspace_id",
            "blob",
            "reported_build_id",
            "dump_timestamp",
            "reported_at",
            "occurred_at",
            "uploaded_at",
            "time_source",
            "current_analysis",
            "latest_attempt",
            "group",
        },
    )
    _assert_model_round_trip(OccurrenceResponse, occurrence)

    canonical = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/analysis")
    canonical_payload = _assert_json_response(canonical, 200)
    assert canonical_payload["analysis_id"] == occurrence["current_analysis"]["id"]
    assert (
        _assert_json_response(
            harness.client.get(f"/api/v1/occurrences/{occurrence_id}/threads"), 200
        )
        == canonical_payload["threads"]
    )
    assert (
        _assert_json_response(
            harness.client.get(f"/api/v1/occurrences/{occurrence_id}/modules"), 200
        )
        == canonical_payload["modules"]
    )

    events = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/events")
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert events.headers["x-accel-buffering"] == "no"
    assert "event: analysis-progress\n" in events.text
    assert f'"occurrence_id":"{occurrence_id}"' in events.text

    group_id = occurrence["group"]["id"]
    group = _assert_json_response(harness.client.get(f"/api/v1/groups/{group_id}"), 200)
    assert group["occurrence_ids"] == [occurrence_id]
    overview = _assert_json_response(
        harness.client.get(f"/api/v1/workspaces/{workspace['id']}/overview"), 200
    )
    assert overview["crash_occurrences"] == 1
    assert _assert_json_response(
        harness.client.get(f"/api/v1/workspaces/{workspace['id']}/symbols/health"), 200
    )
    rules = _assert_json_response(
        harness.client.get(f"/api/v1/workspaces/{workspace['id']}/in-app-rules"), 200
    )
    assert rules == {
        "workspace_id": workspace["id"],
        "version": 0,
        "include_modules": [],
        "exclude_modules": [],
    }

    queued = _assert_json_response(
        harness.client.post(
            f"/api/v1/workspaces/{workspace['id']}/symbols/reindex", json={"build_id": build["id"]}
        ),
        202,
        {"status", "attempt_id", "created"},
    )
    assert queued["status"] == "QUEUED"

    harness.app.state.settings.raw_download_enabled = True
    download = _assert_json_response(
        harness.client.get(f"/api/v1/occurrences/{occurrence_id}/download"),
        200,
        {"url", "expires_at"},
    )
    assert download["url"]

    missing = harness.client.get(
        "/api/v1/workspaces/wsp_missing",
        headers={"X-Request-ID": request_id},
    )
    error = _assert_json_response(missing, 404, {"error"}, request_id=request_id)
    assert set(error["error"]) == {"code", "message", "details"}
    assert error["error"]["code"] == "NOT_FOUND"


def test_upload_init_old_new_server_client_quadrants() -> None:
    class LegacyUploadClient(BaseModel):
        model_config = ConfigDict(extra="ignore")

        upload_id: str
        method: str
        url: str
        headers: dict[str, str]
        expires_in: int
        multipart: dict[str, Any] | None = None

    old_server = {
        "upload_id": "upl_old",
        "method": "PUT",
        "url": "",
        "headers": {},
        "expires_in": 900,
        "multipart": {
            "upload_id": "mp_old",
            "parts": [{"part_number": 1, "url": "http://upload.invalid/1"}],
        },
    }
    new_server = {
        **old_server,
        "upload_id": "upl_new",
        "multipart": {**old_server["multipart"], "part_size": 5},
    }

    assert LegacyUploadClient.model_validate(old_server).upload_id == "upl_old"
    assert LegacyUploadClient.model_validate(new_server).upload_id == "upl_new"
    assert UploadInitResponse.model_validate(old_server).multipart is not None
    decoded_new = UploadInitResponse.model_validate(new_server)
    assert decoded_new.multipart is not None
    assert decoded_new.multipart.part_size == 5


def test_openapi_has_stable_operations_named_responses_and_single_source_canonical(
    harness: Phase1Harness,
) -> None:
    document = harness.app.openapi()
    expected_operations = {
        "capabilities_api_v2_capabilities_get",
        "get_analysis_api_v2_occurrences__occurrence_id__analysis_get",
        "get_run_analysis_api_v2_runs__run_id__analysis_get",
        "get_threads_api_v2_occurrences__occurrence_id__threads_get",
        "get_modules_api_v2_occurrences__occurrence_id__modules_get",
        "retry_analysis_dispatch_api_v1_analysis_runs__run_id__retry_dispatch_post",
        "download_artifact_api_v1_artifacts__artifact_id__download_get",
        "get_build_api_v1_builds__build_id__get",
        "init_artifact_upload_api_v1_builds__build_id__artifacts_uploads_init_post",
        "init_artifact_delivery_api_v1_builds__build_id__artifacts_deliveries_init_post",
        "init_artifact_delivery_v2_api_v1_builds__build_id__artifacts_deliveries_v2_init_post",
        "build_ci_status_api_v1_builds__build_id__ci_status_get",
        "put_manifest_api_v1_builds__build_id__manifest_put",
        "list_artifacts_api_v1_builds__build_id__symbols_get",
        "ci_producer_matrix_api_v1_ci_producers_get",
        "artifact_producer_matrix_api_v1_artifact_producers_get",
        "get_build_publication_api_v1_build_publications__publication_id__get",
        "get_build_publication_status_api_v1_builds__build_id__publication_status_get",
        "create_build_publication_api_v1_workspaces__workspace_id__build_publications_post",
        "get_group_api_v1_groups__group_id__get",
        "patch_group_api_v1_groups__group_id__patch",
        "unsupported_group_edit_api_v1_groups__group_id__merge_post",
        "unsupported_group_edit_api_v1_groups__group_id__split_post",
        "get_occurrence_api_v1_occurrences__occurrence_id__get",
        "get_analysis_api_v1_occurrences__occurrence_id__analysis_get",
        "download_dump_api_v1_occurrences__occurrence_id__download_get",
        "occurrence_events_api_v1_occurrences__occurrence_id__events_get",
        "get_modules_api_v1_occurrences__occurrence_id__modules_get",
        "reprocess_api_v1_occurrences__occurrence_id__reprocess_post",
        "get_threads_api_v1_occurrences__occurrence_id__threads_get",
        "patch_occurrence_time_api_v1_occurrences__occurrence_id__time_patch",
        "get_upload_api_v1_uploads__upload_id__get",
        "finish_upload_api_v1_uploads__upload_id__complete_post",
        "list_workspaces_api_v1_workspaces_get",
        "create_workspace_api_v1_workspaces_post",
        "get_workspace_api_v1_workspaces__workspace_id__get",
        "platform_overview_api_v1_platform_overview_get",
        "list_occurrences_api_v1_workspaces__workspace_id__occurrences_get",
        "list_builds_api_v1_workspaces__workspace_id__builds_get",
        "create_build_api_v1_workspaces__workspace_id__builds_post",
        "init_dump_upload_api_v1_workspaces__workspace_id__dumps_uploads_init_post",
        "list_groups_api_v1_workspaces__workspace_id__groups_get",
        "get_in_app_rules_api_v1_workspaces__workspace_id__in_app_rules_get",
        "update_in_app_rules_api_v1_workspaces__workspace_id__in_app_rules_put",
        "workspace_overview_api_v1_workspaces__workspace_id__overview_get",
        "symbol_health_api_v1_workspaces__workspace_id__symbols_health_get",
        "missing_symbols_api_v1_workspaces__workspace_id__symbols_missing_get",
        "reindex_symbols_api_v1_workspaces__workspace_id__symbols_reindex_post",
        "batch_reprocess_symbols_api_v1_workspaces__workspace_id__symbols_reprocess_post",
        "get_analysis_demand_api_v2_workspaces__workspace_id__"
        "occurrences__occurrence_id__analysis_demand_get",
        "restart_analysis_demand_api_v2_workspaces__workspace_id__"
        "occurrences__occurrence_id__analysis_demand_restarts_post",
        "get_analysis_differences_api_v2_workspaces__workspace_id__"
        "occurrences__occurrence_id__analysis_history__run_id__differences_get",
        "get_import_api_v2_symbol_imports__import_id__get",
        "get_pair_origins_api_v2_symbol_catalog_pairs__pair_id__origins_get",
        "get_review_evidence_api_v2_symbol_catalog_pairs__pair_id__reviews__review_id__evidence_get",
        "initialize_submission_api_v2_workspaces__workspace_id__uploads_post",
        "list_analysis_history_api_v2_workspaces__workspace_id__"
        "occurrences__occurrence_id__analysis_history_get",
        "list_pair_reviews_api_v2_symbol_catalog_pairs__pair_id__reviews_get",
        "list_submissions_api_v2_workspaces__workspace_id__occurrences__occurrence_id__submissions_get",
        "post_complete_api_v2_symbol_imports__import_id__items__item_id__complete_post",
        "post_import_api_v2_symbol_imports_post",
        "post_module_role_api_v2_workspaces__workspace_id__module_roles_post",
        "put_file_api_v2_symbol_imports__import_id__items__item_id__files__kind__put",
        "submit_pair_review_api_v2_symbol_catalog_pairs__pair_id__reviews_post",
        "get_result_review_api_v2_workspaces__workspace_id__"
        "occurrences__occurrence_id__result_reviews__review_id__get",
        "submit_result_review_api_v2_workspaces__workspace_id__"
        "occurrences__occurrence_id__result_reviews_post",
        "list_result_reviews_api_v2_workspaces__workspace_id__"
        "occurrences__occurrence_id__result_reviews_get",
        "get_result_review_evidence_api_v2_workspaces__workspace_id__"
        "occurrences__occurrence_id__result_reviews__review_id__evidence_get",
    }
    operations = {
        operation["operationId"]
        for path in document["paths"].values()
        for method, operation in path.items()
        if method != "parameters"
    }
    assert operations == expected_operations

    excluded_success = {
        ("/api/v1/groups/{group_id}/merge", "post"),
        ("/api/v1/groups/{group_id}/split", "post"),
    }
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if method == "parameters" or (path, method) in excluded_success:
                continue
            success = next(
                response
                for status, response in operation["responses"].items()
                if status.startswith("2")
            )
            content = success.get("content", {})
            expected_media = "text/event-stream" if path.endswith("/events") else "application/json"
            assert set(content) == {expected_media}, (path, method, content)
            assert content[expected_media].get("schema"), (path, method)
            error_422 = operation["responses"]["422"]
            assert set(error_422["content"]) == {"application/json"}
            assert error_422["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorEnvelopeResponse"
            }

    analysis_response = document["paths"]["/api/v1/occurrences/{occurrence_id}/analysis"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert analysis_response == {"$ref": f"#/components/schemas/{CANONICAL_COMPONENT}"}
    components = document["components"]["schemas"]
    canonical = components[CANONICAL_COMPONENT]
    contract_path = Path(harness.settings.schema_root) / "analysis-result-v1.schema.json"
    assert canonical["x-crashcap-source-contract"] == contract_path.name
    assert (
        canonical["x-crashcap-source-sha256"]
        == hashlib.sha256(contract_path.read_bytes()).hexdigest()
    )
    assert "$defs" not in canonical
    assert "CanonicalThread" in components
    assert "CanonicalModule" in components
    assert not any(name.startswith("CanonicalAnalysisResultResponse") for name in components)
