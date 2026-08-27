export interface paths {
    "/api/v1/analysis-runs/{run_id}/retry-dispatch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retry Analysis Dispatch */
        post: operations["retry_analysis_dispatch_api_v1_analysis_runs__run_id__retry_dispatch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifact-producers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Artifact Producer Matrix */
        get: operations["artifact_producer_matrix_api_v1_artifact_producers_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts/{artifact_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download Artifact */
        get: operations["download_artifact_api_v1_artifacts__artifact_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/build-publications/{publication_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Build Publication */
        get: operations["get_build_publication_api_v1_build_publications__publication_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/builds/{build_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Build */
        get: operations["get_build_api_v1_builds__build_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/builds/{build_id}/artifacts/deliveries-v2:init": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Init Artifact Delivery V2 */
        post: operations["init_artifact_delivery_v2_api_v1_builds__build_id__artifacts_deliveries_v2_init_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/builds/{build_id}/artifacts/deliveries:init": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Init Artifact Delivery */
        post: operations["init_artifact_delivery_api_v1_builds__build_id__artifacts_deliveries_init_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/builds/{build_id}/artifacts/uploads:init": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Init Artifact Upload */
        post: operations["init_artifact_upload_api_v1_builds__build_id__artifacts_uploads_init_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/builds/{build_id}/ci-status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Build Ci Status */
        get: operations["build_ci_status_api_v1_builds__build_id__ci_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/builds/{build_id}/manifest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Put Manifest */
        put: operations["put_manifest_api_v1_builds__build_id__manifest_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/builds/{build_id}/publication-status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Build Publication Status */
        get: operations["get_build_publication_status_api_v1_builds__build_id__publication_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/builds/{build_id}/symbols": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Artifacts */
        get: operations["list_artifacts_api_v1_builds__build_id__symbols_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/ci/producers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ci Producer Matrix */
        get: operations["ci_producer_matrix_api_v1_ci_producers_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/groups/{group_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Group */
        get: operations["get_group_api_v1_groups__group_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Patch Group */
        patch: operations["patch_group_api_v1_groups__group_id__patch"];
        trace?: never;
    };
    "/api/v1/groups/{group_id}/merge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Unsupported Group Edit */
        post: operations["unsupported_group_edit_api_v1_groups__group_id__merge_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/groups/{group_id}/split": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Unsupported Group Edit */
        post: operations["unsupported_group_edit_api_v1_groups__group_id__split_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/occurrences/{occurrence_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Occurrence */
        get: operations["get_occurrence_api_v1_occurrences__occurrence_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/occurrences/{occurrence_id}/analysis": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Analysis */
        get: operations["get_analysis_api_v1_occurrences__occurrence_id__analysis_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/occurrences/{occurrence_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download Dump */
        get: operations["download_dump_api_v1_occurrences__occurrence_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/occurrences/{occurrence_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Occurrence Events */
        get: operations["occurrence_events_api_v1_occurrences__occurrence_id__events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/occurrences/{occurrence_id}/modules": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Modules */
        get: operations["get_modules_api_v1_occurrences__occurrence_id__modules_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/occurrences/{occurrence_id}/reprocess": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reprocess */
        post: operations["reprocess_api_v1_occurrences__occurrence_id__reprocess_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/occurrences/{occurrence_id}/threads": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Threads */
        get: operations["get_threads_api_v1_occurrences__occurrence_id__threads_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/occurrences/{occurrence_id}/time": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Patch Occurrence Time */
        patch: operations["patch_occurrence_time_api_v1_occurrences__occurrence_id__time_patch"];
        trace?: never;
    };
    "/api/v1/uploads/{upload_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Upload */
        get: operations["get_upload_api_v1_uploads__upload_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/uploads/{upload_id}/complete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Finish Upload */
        post: operations["finish_upload_api_v1_uploads__upload_id__complete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Workspaces */
        get: operations["list_workspaces_api_v1_workspaces_get"];
        put?: never;
        /** Create Workspace */
        post: operations["create_workspace_api_v1_workspaces_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Workspace */
        get: operations["get_workspace_api_v1_workspaces__workspace_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/build-publications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Build Publication */
        post: operations["create_build_publication_api_v1_workspaces__workspace_id__build_publications_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/builds": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Builds */
        get: operations["list_builds_api_v1_workspaces__workspace_id__builds_get"];
        put?: never;
        /** Create Build */
        post: operations["create_build_api_v1_workspaces__workspace_id__builds_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/dumps/uploads:init": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Init Dump Upload */
        post: operations["init_dump_upload_api_v1_workspaces__workspace_id__dumps_uploads_init_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/groups": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Groups */
        get: operations["list_groups_api_v1_workspaces__workspace_id__groups_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/in-app-rules": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get In App Rules */
        get: operations["get_in_app_rules_api_v1_workspaces__workspace_id__in_app_rules_get"];
        /** Update In App Rules */
        put: operations["update_in_app_rules_api_v1_workspaces__workspace_id__in_app_rules_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Workspace Overview */
        get: operations["workspace_overview_api_v1_workspaces__workspace_id__overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/symbols/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Symbol Health */
        get: operations["symbol_health_api_v1_workspaces__workspace_id__symbols_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/symbols/missing": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Missing Symbols */
        get: operations["missing_symbols_api_v1_workspaces__workspace_id__symbols_missing_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/symbols/reindex": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reindex Symbols */
        post: operations["reindex_symbols_api_v1_workspaces__workspace_id__symbols_reindex_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/symbols/reprocess": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Batch Reprocess Symbols */
        post: operations["batch_reprocess_symbols_api_v1_workspaces__workspace_id__symbols_reprocess_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AnalysisRunResponse */
        AnalysisRunResponse: {
            /** Duration Ms */
            duration_ms: number | null;
            /** Error Code */
            error_code: string | null;
            /** Error Detail */
            error_detail: string | null;
            /** Finished At */
            finished_at: string | null;
            /** Id */
            id: string;
            /** Quality Score */
            quality_score: number | null;
            /**
             * Resolution Method
             * @enum {string}
             */
            resolution_method: "reported" | "auto_unique" | "manual" | "ambiguous" | "unresolved";
            /** Resolved Build Id */
            resolved_build_id: string | null;
            /** Started At */
            started_at: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "UPLOADED" | "VALIDATING" | "INSPECTED" | "MATCHING_SYMBOLS" | "WAITING_FOR_SYMBOLS" | "SYMBOLS_READY" | "QUEUED" | "ANALYZING" | "NORMALIZING" | "GROUPING" | "COMPLETE" | "PARTIAL" | "FAILED" | "REJECTED" | "CANCELLED" | "TIMEOUT" | "OOM";
        };
        /** ArtifactDeliveryInit */
        ArtifactDeliveryInit: {
            /**
             * File Kind
             * @enum {string}
             */
            file_kind: "pe" | "pdb";
            /** Filename */
            filename: string;
            /** Sha256 */
            sha256: string;
            /** Size */
            size: number;
        };
        /** ArtifactDeliveryLogical */
        ArtifactDeliveryLogical: {
            /** Sha256 */
            sha256: string;
            /** Size */
            size: number;
        };
        /** ArtifactDeliveryReusedResponse */
        ArtifactDeliveryReusedResponse: {
            /** Artifact Blob Id */
            artifact_blob_id: string;
            /** Artifact Id */
            artifact_id: string;
            /**
             * Delivery
             * @constant
             */
            delivery: "reused";
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            disposition: "reused";
        };
        /** ArtifactDeliveryUploadResponse */
        ArtifactDeliveryUploadResponse: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            disposition: "upload";
            /** Expires In */
            expires_in: number;
            /** Headers */
            headers: {
                [key: string]: string;
            };
            /**
             * Method
             * @enum {string}
             */
            method: "PUT" | "POST";
            multipart?: components["schemas"]["PresignedMultipartResponse"] | null;
            /** Upload Id */
            upload_id: string;
            /** Url */
            url: string;
        };
        /** ArtifactDeliveryV2Init */
        ArtifactDeliveryV2Init: {
            /**
             * File Kind
             * @enum {string}
             */
            file_kind: "pe" | "pdb";
            /** Filename */
            filename: string;
            logical: components["schemas"]["ArtifactDeliveryLogical"];
            wire: components["schemas"]["ArtifactDeliveryWire"];
        };
        /** ArtifactDeliveryV2UploadResponse */
        ArtifactDeliveryV2UploadResponse: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            disposition: "upload";
            /** Expires In */
            expires_in: number;
            /** Headers */
            headers: {
                [key: string]: string;
            };
            /**
             * Method
             * @enum {string}
             */
            method: "PUT" | "POST";
            multipart?: components["schemas"]["PresignedMultipartResponse"] | null;
            /** Upload Id */
            upload_id: string;
            /** Url */
            url: string;
            /**
             * Wire Encoding
             * @enum {string}
             */
            wire_encoding: "identity" | "zstd-v1";
            /** Wire Size */
            wire_size: number;
        };
        /** ArtifactDeliveryWaitResponse */
        ArtifactDeliveryWaitResponse: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            disposition: "wait";
            /** Lease Expires At */
            lease_expires_at: string;
            /** Retry After Seconds */
            retry_after_seconds: number;
        };
        /** ArtifactDeliveryWire */
        ArtifactDeliveryWire: {
            /**
             * Encoding
             * @enum {string}
             */
            encoding: "identity" | "zstd-v1";
            /** Sha256 */
            sha256: string;
            /** Size */
            size: number;
        };
        /** ArtifactExpectationCreate */
        ArtifactExpectationCreate: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "pe" | "pdb";
            /** Logical Name */
            logical_name: string;
            /** Module Code File */
            module_code_file: string;
            /** Sha256 */
            sha256: string;
            /** Size */
            size: number;
        };
        /** ArtifactExpectationResponse */
        ArtifactExpectationResponse: {
            /** Artifact Blob Id */
            artifact_blob_id: string | null;
            /** Artifact Id */
            artifact_id: string | null;
            /** Delivery */
            delivery: ("uploaded" | "reused" | "backfilled") | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "pe" | "pdb";
            /** Logical Name */
            logical_name: string;
            /** Module Code File */
            module_code_file: string;
            /** Module Id */
            module_id: string;
            /** Rejection Reason */
            rejection_reason: string | null;
            /** Sha256 */
            sha256: string;
            /** Size */
            size: number;
            /**
             * Status
             * @enum {string}
             */
            status: "missing" | "uploading" | "verifying" | "verified" | "rejected";
            /** Upload Id */
            upload_id: string | null;
        };
        /** ArtifactProducerResponse */
        ArtifactProducerResponse: {
            /** Artifact Delivery Contracts */
            artifact_delivery_contracts: ("artifact-delivery-v1" | "artifact-delivery-v2")[];
            /** Artifact Format */
            artifact_format: string;
            /** Build Publications Enabled */
            build_publications_enabled: boolean;
            /** Fixture Suite */
            fixture_suite: string | null;
            /** Gate */
            gate: string;
            /** Minimum Client Version */
            minimum_client_version: string;
            /**
             * Producer
             * @enum {string}
             */
            producer: "msvc" | "clang-cl" | "crashpad";
            /** Publication Contracts */
            publication_contracts: "1.0"[];
            /**
             * Status
             * @enum {string}
             */
            status: "supported" | "experimental";
        };
        /** ArtifactResponse */
        ArtifactResponse: {
            /** Artifact Blob Id */
            artifact_blob_id: string | null;
            /** Code Id */
            code_id: string | null;
            /** Created At */
            created_at: string;
            /** Debug Id */
            debug_id: string | null;
            /** Delivery */
            delivery: ("uploaded" | "reused" | "backfilled") | null;
            /** Id */
            id: string;
            ingest_metadata: components["schemas"]["SourceBundleIngestMetadataResponse"] | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "pe" | "pdb" | "source_bundle";
            /** Logical Name */
            logical_name: string;
            /** Logical Size */
            logical_size: number;
            /** Module Id */
            module_id: string | null;
            /**
             * Payload Encoding
             * @enum {string}
             */
            payload_encoding: "identity" | "zstd-v1";
            /** Savings Bytes */
            savings_bytes: number;
            /** Savings Ratio */
            savings_ratio: number;
            /** Sha256 */
            sha256: string;
            /** Size */
            size: number;
            /**
             * Storage Status
             * @enum {string}
             */
            storage_status: "legacy" | "pending" | "verified" | "missing" | "rejected";
            /** Stored Size */
            stored_size: number;
            /**
             * Verification Status
             * @enum {string}
             */
            verification_status: "pending" | "verified" | "rejected_fastlink" | "pdb_mismatch" | "pe_mismatch" | "corrupted" | "rejected_format";
        };
        /** ArtifactUploadInit */
        ArtifactUploadInit: {
            /**
             * File Kind
             * @enum {string}
             */
            file_kind: "pe" | "pdb" | "source_bundle";
            /** Filename */
            filename: string;
            /** Sha256 */
            sha256?: string | null;
            /** Size */
            size: number;
        };
        /** BatchReprocessResponse */
        BatchReprocessResponse: {
            /** Affected Occurrence Count */
            affected_occurrence_count: number;
            /** Created Run Count */
            created_run_count: number;
            /** Occurrence Ids */
            occurrence_ids: string[];
            /** Run Ids */
            run_ids: string[];
            /** Workspace Id */
            workspace_id: string;
        };
        /** BlobResponse */
        BlobResponse: {
            /** Deleted At */
            deleted_at: string | null;
            /**
             * Dump Kind
             * @enum {string}
             */
            dump_kind: "user_minidump" | "kernel" | "unknown_binary";
            /** Expires At */
            expires_at: string | null;
            /** Id */
            id: string;
            /** Sha256 */
            sha256: string;
            /** Size */
            size: number;
            /** Uploaded At */
            uploaded_at: string;
            /**
             * Verification Status
             * @enum {string}
             */
            verification_status: "initialized" | "uploading" | "uploaded" | "verifying" | "accepted" | "quarantined" | "rejected";
        };
        /** Body_reindex_symbols_api_v1_workspaces__workspace_id__symbols_reindex_post */
        Body_reindex_symbols_api_v1_workspaces__workspace_id__symbols_reindex_post: {
            /** Build Id */
            build_id?: string | null;
        };
        /** BuildCiStatusResponse */
        BuildCiStatusResponse: {
            /** Build Id */
            build_id: string;
            /** Manifest Present */
            manifest_present: boolean;
            /** Manifest Schema Version */
            manifest_schema_version: ("1.0" | "2.0") | null;
            /** Missing Artifacts */
            missing_artifacts: components["schemas"]["MissingArtifactResponse"][];
            /** Module Count */
            module_count: number;
            /** Producer */
            producer: ("msvc" | "clang-cl" | "crashpad") | null;
            /**
             * Producer Status
             * @enum {string}
             */
            producer_status: "supported" | "experimental" | "unregistered";
            /** Ready */
            ready: boolean;
            /** Rejected Artifacts */
            rejected_artifacts: components["schemas"]["RejectedArtifactResponse"][];
            /**
             * Source Bundle Status
             * @enum {string}
             */
            source_bundle_status: "not_declared" | "verified" | "pending" | "missing_or_rejected";
        };
        /** BuildCreate */
        BuildCreate: {
            /**
             * Architecture
             * @default x86_64
             * @constant
             */
            architecture: "x86_64";
            /** Build Number */
            build_number?: string | null;
            /** Channel */
            channel?: string | null;
            /** Commit Sha */
            commit_sha?: string | null;
            /** Producer */
            producer?: ("msvc" | "clang-cl" | "crashpad") | null;
            /** Producer Build Id */
            producer_build_id?: string | null;
            /** Toolchain */
            toolchain?: string | null;
            /** Version */
            version: string;
        };
        /** BuildDistributionResponse */
        BuildDistributionResponse: {
            /** Build Id */
            build_id: string;
            /** Count */
            count: number;
            /** Version */
            version: string;
        };
        /** BuildModuleResponse */
        BuildModuleResponse: {
            /** Artifact Count */
            artifact_count: number;
            /** Code File */
            code_file: string;
            /** Code Id */
            code_id: string | null;
            /** Debug File */
            debug_file: string;
            /** Debug Id */
            debug_id: string | null;
            /** Id */
            id: string;
            /** In App */
            in_app: boolean;
            /** Missing Occurrence Count */
            missing_occurrence_count: number;
            /**
             * Role
             * @enum {string}
             */
            role: "entrypoint" | "owned" | "dependency";
        };
        /** BuildPublicationCreate */
        BuildPublicationCreate: {
            /** Artifacts */
            artifacts: components["schemas"]["ArtifactExpectationCreate"][];
            /** Client Publication Id */
            client_publication_id: string;
            /** Client Version */
            client_version: string;
            git: components["schemas"]["PublicationGitState"];
            /** Manifest */
            manifest: {
                [key: string]: unknown;
            };
            /**
             * Origin
             * @enum {string}
             */
            origin: "local" | "ci";
            /**
             * Schema Version
             * @constant
             */
            schema_version: "1.0";
        };
        /** BuildPublicationStatusResponse */
        BuildPublicationStatusResponse: {
            /** Build Id */
            build_id: string;
            /** Content Fingerprint */
            content_fingerprint: string;
            /** Expected Artifacts */
            expected_artifacts: components["schemas"]["ArtifactExpectationResponse"][];
            /**
             * Fingerprint Version
             * @constant
             */
            fingerprint_version: "build-content-v1";
            /**
             * Identity Mode
             * @constant
             */
            identity_mode: "content_v1";
            /** Missing Artifacts */
            missing_artifacts: components["schemas"]["ArtifactExpectationResponse"][];
            publication: components["schemas"]["BuildPublicationSummaryResponse"] | null;
            /** Publications */
            publications: components["schemas"]["BuildPublicationSummaryResponse"][];
            /** Ready */
            ready: boolean;
            /** Rejected Artifacts */
            rejected_artifacts: components["schemas"]["ArtifactExpectationResponse"][];
            /** Sealed At */
            sealed_at: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "registered" | "uploading" | "verifying" | "ready" | "rejected";
        };
        /** BuildPublicationSummaryResponse */
        BuildPublicationSummaryResponse: {
            /** Build Id */
            build_id: string;
            /** Client Publication Id */
            client_publication_id: string;
            /** Client Version */
            client_version: string;
            /** Created At */
            created_at: string;
            /** Git Revision */
            git_revision: string | null;
            /**
             * Git Worktree State
             * @enum {string}
             */
            git_worktree_state: "clean" | "dirty" | "unknown";
            /** Id */
            id: string;
            /** Last Seen At */
            last_seen_at: string;
            /**
             * Origin
             * @enum {string}
             */
            origin: "local" | "ci";
            /** Workspace Id */
            workspace_id: string;
        };
        /** BuildResponse */
        BuildResponse: {
            /**
             * Architecture
             * @constant
             */
            architecture: "x86_64";
            /** Artifacts */
            artifacts: components["schemas"]["ArtifactResponse"][];
            /** Build Number */
            build_number: string | null;
            /** Channel */
            channel: string | null;
            /** Commit Sha */
            commit_sha: string | null;
            /** Content Fingerprint */
            content_fingerprint: string | null;
            /** Created At */
            created_at: string;
            /** Fingerprint Version */
            fingerprint_version: "build-content-v1" | null;
            /** Groups */
            groups: components["schemas"]["GroupSummaryResponse"][];
            /** Id */
            id: string;
            /**
             * Identity Mode
             * @enum {string}
             */
            identity_mode: "legacy" | "content_v1";
            /** Manifest Object Key */
            manifest_object_key: string | null;
            /** Manifest Schema Version */
            manifest_schema_version: ("1.0" | "2.0") | null;
            /** Modules */
            modules: components["schemas"]["BuildModuleResponse"][];
            /** Producer */
            producer: ("msvc" | "clang-cl" | "crashpad") | null;
            /** Producer Build Id */
            producer_build_id: string | null;
            /** Sealed At */
            sealed_at: string | null;
            source_bundle_config: components["schemas"]["SourceBundleDescriptorResponse"] | null;
            /** Toolchain */
            toolchain: string | null;
            /** Version */
            version: string;
            /** Workspace Id */
            workspace_id: string;
        };
        /**
         * Crash-Cap Canonical Analysis Result stable v1.0
         * @description Stable v1.0 platform-facing analysis contract frozen after the Phase 0 Golden Dump gate. Engine-native JSON is stored separately.
         */
        CanonicalAnalysisResult: {
            /** @description Immutable analysis run id. */
            analysis_id: string;
            build_resolution: components["schemas"]["CanonicalBuildResolution"];
            crash: {
                /** @enum {string|null} */
                access_type?: "read" | "write" | "execute" | "readwrite" | null;
                address?: components["schemas"]["CanonicalHexAddr"];
                exception_code?: string | null;
                exception_name?: string | null;
                fault_module?: string | null;
                fault_module_debug_id?: string | null;
                thread_id?: number | null;
                /** @enum {string} */
                type: "crash" | "hang" | "unknown";
                /** @enum {string} */
                type_evidence: "exception_stream" | "reported_hang" | "insufficient" | "other";
            };
            dump: {
                blob_id: string;
                /** @enum {string|null} */
                capture_profile?: "light-crash" | "rich-crash" | "hang" | "full-memory" | null;
                dump_timestamp?: components["schemas"]["CanonicalNullableTimestamp"];
                /** @enum {string} */
                kind: "user_minidump" | "kernel" | "unknown_binary";
                /** Format: date-time */
                occurred_at: string;
                reported_at?: components["schemas"]["CanonicalNullableTimestamp"];
                sha256: string;
                size: number;
                /** @enum {string} */
                time_source: "dump" | "reported" | "uploaded" | "manual";
                /** Format: date-time */
                uploaded_at: string;
            };
            engine: {
                core_image_digest: string;
                core_version: string;
                grouping_version: string;
                normalization_version: string;
                symbolicator_version: string;
            };
            fingerprints: {
                algorithm: string;
                /** @description Null unless a matched fault module and at least one non-scan in-app frame exist. */
                exact: string | null;
                /** @description Reserved. Phase 1 is always null. */
                family: null;
            };
            modules: components["schemas"]["CanonicalModule"][];
            occurrence_id: string;
            process: {
                /** @enum {string} */
                architecture: "x86_64" | "x86" | "arm64" | "unknown";
                os: string;
                os_version?: string | null;
                pid?: number | null;
                uptime_seconds?: number | null;
            };
            quality: {
                artifact_completeness: number;
                score: number;
                symbol_coverage: number;
                unwind_reliability: number;
                warnings: components["schemas"]["CanonicalQualityWarning"][];
            };
            /** @constant */
            schema_version: "1.0";
            threads: components["schemas"]["CanonicalThread"][];
            workspace_id: string;
        } & unknown;
        CanonicalBuildResolution: {
            evidence: {
                candidate_build_ids: string[];
                conflicting_modules: string[];
                matched_entrypoints: string[];
                matched_owned_modules: string[];
                note?: string | null;
            };
            reported_build_id: string | null;
            /** @enum {string} */
            resolution_method: "reported" | "auto_unique" | "manual" | "ambiguous" | "unresolved";
            resolved_build_id: string | null;
        };
        CanonicalFrame: {
            file?: string | null;
            function?: string | null;
            function_normalized?: string | null;
            function_offset?: number | null;
            function_raw?: string | null;
            in_app: boolean;
            index: number;
            inline?: boolean;
            instruction_addr: string;
            line?: number | null;
            module?: string | null;
            module_debug_id?: string | null;
            relative_addr?: components["schemas"]["CanonicalHexAddr"];
            /** @description Reserved. Phase 1 omits or sets null. */
            source_context?: {
                line?: string;
                post?: string[];
                pre?: string[];
            } | null;
            trust: components["schemas"]["CanonicalTrust"];
        };
        /** CanonicalFrameResponse */
        CanonicalFrameResponse: {
            /** File */
            file?: string | null;
            /** Function */
            function?: string | null;
            /** Function Normalized */
            function_normalized?: string | null;
            /** Function Offset */
            function_offset?: number | null;
            /** Function Raw */
            function_raw?: string | null;
            /** In App */
            in_app: boolean;
            /** Index */
            index: number;
            /** Inline */
            inline?: boolean | null;
            /** Instruction Addr */
            instruction_addr: string;
            /** Line */
            line?: number | null;
            /** Module */
            module?: string | null;
            /** Module Debug Id */
            module_debug_id?: string | null;
            /** Relative Addr */
            relative_addr?: string | null;
            source_context?: components["schemas"]["SourceContextResponse"] | null;
            /**
             * Trust
             * @enum {string}
             */
            trust: "context" | "cfi" | "frame_pointer" | "scan" | "unknown";
        };
        CanonicalHexAddr: string | null;
        CanonicalModule: {
            artifact_ids: string[];
            code_file: string;
            code_id?: string | null;
            debug_file?: string | null;
            debug_id?: string | null;
            image_base?: components["schemas"]["CanonicalHexAddr"];
            image_size?: number | null;
            in_app: boolean;
            role: components["schemas"]["CanonicalModuleRole"];
            /** @enum {string} */
            status: "matched" | "missing_pe" | "missing_pdb" | "pdb_mismatch" | "pe_mismatch" | "corrupted" | "system_symbol_pending" | "unsupported";
        };
        /** @enum {string} */
        CanonicalModuleRole: "entrypoint" | "owned" | "dependency" | "system" | "unknown";
        /** Format: date-time */
        CanonicalNullableTimestamp: string | null;
        CanonicalQualityWarning: {
            /** @enum {string} */
            code: "missing_pe" | "missing_pdb" | "pdb_mismatch" | "pe_mismatch" | "missing_pe_unwind" | "system_symbol_pending" | "system_symbol_failed" | "symbolicator_failed" | "truncated_dump" | "scan_frames" | "module_limit_truncated" | "unsupported_inline" | "ambiguous_build" | "unresolved_build" | "unknown_crash_type" | "unclassified_exact" | "other";
            debug_id?: string | null;
            message: string;
            module?: string | null;
        };
        CanonicalThread: {
            frames: components["schemas"]["CanonicalFrame"][];
            id: number;
            is_crashing: boolean;
            name?: string | null;
        };
        /** @enum {string} */
        CanonicalTrust: "context" | "cfi" | "frame_pointer" | "scan" | "unknown";
        /** DumpUploadInit */
        DumpUploadInit: {
            /** Capture Profile */
            capture_profile?: ("light-crash" | "rich-crash" | "hang" | "full-memory") | null;
            /** Filename */
            filename: string;
            /** Reported At */
            reported_at?: string | null;
            /** Reported Build Id */
            reported_build_id?: string | null;
            /** Sha256 */
            sha256?: string | null;
            /** Size */
            size: number;
        };
        /** ErrorDetailResponse */
        ErrorDetailResponse: {
            /** Code */
            code: string;
            /** Details */
            details: {
                [key: string]: unknown;
            };
            /** Message */
            message: string;
        };
        /** ErrorEnvelopeResponse */
        ErrorEnvelopeResponse: {
            error: components["schemas"]["ErrorDetailResponse"];
        };
        /** GroupDetailResponse */
        GroupDetailResponse: {
            /** Build Distribution */
            build_distribution: components["schemas"]["BuildDistributionResponse"][];
            /** Fingerprint */
            fingerprint: string;
            /** First Build Id */
            first_build_id: string | null;
            /** First Seen */
            first_seen: string;
            /**
             * Group Type
             * @constant
             */
            group_type: "exact";
            /** Id */
            id: string;
            /** Issue Url */
            issue_url: string | null;
            /** Last Build Id */
            last_build_id: string | null;
            /** Last Seen */
            last_seen: string;
            /** Occurrence Count */
            occurrence_count: number;
            /** Occurrence Ids */
            occurrence_ids: string[];
            /** Owner */
            owner: string | null;
            /** Representative Stack */
            representative_stack: components["schemas"]["CanonicalFrameResponse"][];
            /**
             * Status
             * @enum {string}
             */
            status: "open" | "investigating" | "fixed" | "ignored";
            /** Title */
            title: string;
            /** Workspace Id */
            workspace_id: string;
        };
        /** GroupPatch */
        GroupPatch: {
            /** Issue Url */
            issue_url?: string | null;
            /** Owner */
            owner?: string | null;
            /** Status */
            status?: ("open" | "investigating" | "fixed" | "ignored") | null;
            /** Title */
            title?: string | null;
        };
        /** GroupSummaryResponse */
        GroupSummaryResponse: {
            /** Fingerprint */
            fingerprint: string;
            /** First Build Id */
            first_build_id: string | null;
            /** First Seen */
            first_seen: string;
            /**
             * Group Type
             * @constant
             */
            group_type: "exact";
            /** Id */
            id: string;
            /** Issue Url */
            issue_url: string | null;
            /** Last Build Id */
            last_build_id: string | null;
            /** Last Seen */
            last_seen: string;
            /** Occurrence Count */
            occurrence_count: number;
            /** Owner */
            owner: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "open" | "investigating" | "fixed" | "ignored";
            /** Title */
            title: string;
            /** Workspace Id */
            workspace_id: string;
        };
        /** InAppRulesBodyResponse */
        InAppRulesBodyResponse: {
            /** Exclude Modules */
            exclude_modules: string[];
            /** Include Modules */
            include_modules: string[];
        };
        /** InAppRulesResponse */
        InAppRulesResponse: {
            /** Exclude Modules */
            exclude_modules: string[];
            /** Include Modules */
            include_modules: string[];
            /** Version */
            version: number;
            /** Workspace Id */
            workspace_id: string;
        };
        /** InAppRulesUpdate */
        InAppRulesUpdate: {
            /** Exclude Modules */
            exclude_modules?: string[];
            /** Include Modules */
            include_modules?: string[];
        };
        /** InAppRulesUpdateResponse */
        InAppRulesUpdateResponse: {
            /** Created Run Count */
            created_run_count: number;
            /** Exclude Modules */
            exclude_modules: string[];
            /** Include Modules */
            include_modules: string[];
            /** Run Ids */
            run_ids?: string[] | null;
            /** Version */
            version: number;
            /** Workspace Id */
            workspace_id: string;
        };
        /** MissingArtifactResponse */
        MissingArtifactResponse: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "pe" | "pdb";
            /** Logical Name */
            logical_name: string;
            /** Module Id */
            module_id: string;
        };
        /** MultipartPart */
        MultipartPart: {
            /** Etag */
            etag: string;
            /** Part Number */
            part_number: number;
        };
        /** OccurrenceResponse */
        OccurrenceResponse: {
            blob: components["schemas"]["BlobResponse"];
            current_analysis: components["schemas"]["AnalysisRunResponse"] | null;
            /** Dump Timestamp */
            dump_timestamp: string | null;
            group: components["schemas"]["GroupSummaryResponse"] | null;
            /** Id */
            id: string;
            latest_attempt: components["schemas"]["AnalysisRunResponse"] | null;
            /** Occurred At */
            occurred_at: string;
            /** Reported At */
            reported_at: string | null;
            /** Reported Build Id */
            reported_build_id: string | null;
            /**
             * Time Source
             * @enum {string}
             */
            time_source: "dump" | "reported" | "uploaded" | "manual";
            /** Uploaded At */
            uploaded_at: string;
            /** Workspace Id */
            workspace_id: string;
        };
        /** OccurrenceTimePatch */
        OccurrenceTimePatch: {
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
        };
        /** OverviewResponse */
        OverviewResponse: {
            /** Average Analysis Duration Ms */
            average_analysis_duration_ms: number;
            /** Crash Occurrences */
            crash_occurrences: number;
            /** Exact Groups */
            exact_groups: number;
            /** Failure Rate */
            failure_rate: number;
            /** Hang Captures */
            hang_captures: number;
            /** Rejected Uploads */
            rejected_uploads: number;
            /** Symbol Completeness */
            symbol_completeness: number;
            /** Top Groups */
            top_groups: components["schemas"]["GroupSummaryResponse"][];
            /** Unclassified */
            unclassified: number;
            /** Unknown Captures */
            unknown_captures: number;
            /** Versions */
            versions: components["schemas"]["VersionCountResponse"][];
            /** Window End */
            window_end: string;
            /** Window Start */
            window_start: string;
        };
        /** PresignedDownloadResponse */
        PresignedDownloadResponse: {
            /** Expires At */
            expires_at: string;
            /** Url */
            url: string;
        };
        /** PresignedMultipartPartResponse */
        PresignedMultipartPartResponse: {
            /** Part Number */
            part_number: number;
            /** Url */
            url: string;
        };
        /** PresignedMultipartResponse */
        PresignedMultipartResponse: {
            /** Part Size */
            part_size?: number | null;
            /** Parts */
            parts: components["schemas"]["PresignedMultipartPartResponse"][];
            /** Upload Id */
            upload_id: string;
        };
        /** ProducerResponse */
        ProducerResponse: {
            /** Artifact Format */
            artifact_format: string;
            /** Fixture Suite */
            fixture_suite: string | null;
            /** Gate */
            gate: string;
            /**
             * Producer
             * @enum {string}
             */
            producer: "msvc" | "clang-cl" | "crashpad";
            /**
             * Status
             * @enum {string}
             */
            status: "supported" | "experimental";
        };
        /** PublicationGitState */
        PublicationGitState: {
            /** Revision */
            revision?: string | null;
            /**
             * Worktree State
             * @enum {string}
             */
            worktree_state: "clean" | "dirty" | "unknown";
        };
        /** QueuedTaskResponse */
        QueuedTaskResponse: {
            /** Attempt Id */
            attempt_id: string;
            /** Created */
            created: boolean;
            /**
             * Status
             * @constant
             */
            status: "QUEUED";
        };
        /** RejectedArtifactResponse */
        RejectedArtifactResponse: {
            /** Artifact Id */
            artifact_id: string;
            /** Logical Name */
            logical_name: string;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "verified" | "rejected_fastlink" | "pdb_mismatch" | "pe_mismatch" | "corrupted" | "rejected_format";
        };
        /** ReprocessRequest */
        ReprocessRequest: {
            /**
             * Force
             * @default false
             */
            force: boolean;
            /** Reported Build Id */
            reported_build_id?: string | null;
        };
        /** ReprocessResponse */
        ReprocessResponse: {
            /** Created */
            created: boolean;
            /** Duration Ms */
            duration_ms: number | null;
            /** Error Code */
            error_code: string | null;
            /** Error Detail */
            error_detail: string | null;
            /** Finished At */
            finished_at: string | null;
            /** Id */
            id: string;
            /** Quality Score */
            quality_score: number | null;
            /**
             * Resolution Method
             * @enum {string}
             */
            resolution_method: "reported" | "auto_unique" | "manual" | "ambiguous" | "unresolved";
            /** Resolved Build Id */
            resolved_build_id: string | null;
            /** Started At */
            started_at: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "UPLOADED" | "VALIDATING" | "INSPECTED" | "MATCHING_SYMBOLS" | "WAITING_FOR_SYMBOLS" | "SYMBOLS_READY" | "QUEUED" | "ANALYZING" | "NORMALIZING" | "GROUPING" | "COMPLETE" | "PARTIAL" | "FAILED" | "REJECTED" | "CANCELLED" | "TIMEOUT" | "OOM";
        };
        /** RetryDispatchResponse */
        RetryDispatchResponse: {
            /** Attempt Id */
            attempt_id: string;
            /**
             * Dispatch State
             * @enum {string}
             */
            dispatch_state: "legacy" | "pending" | "reopened" | "active" | "terminal";
            /** Run Id */
            run_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "UPLOADED" | "VALIDATING" | "INSPECTED" | "MATCHING_SYMBOLS" | "WAITING_FOR_SYMBOLS" | "SYMBOLS_READY" | "QUEUED" | "ANALYZING" | "NORMALIZING" | "GROUPING" | "COMPLETE" | "PARTIAL" | "FAILED" | "REJECTED" | "CANCELLED" | "TIMEOUT" | "OOM";
        };
        /** SourceBundleDescriptorResponse */
        SourceBundleDescriptorResponse: {
            /** Archive */
            archive: string;
            /**
             * Context Lines
             * @default 3
             */
            context_lines: number;
            /**
             * Schema Version
             * @constant
             */
            schema_version: "1.0";
            /** Source Root */
            source_root: string;
            /** Strip Prefixes */
            strip_prefixes?: string[];
        };
        /** SourceBundleIngestMetadataResponse */
        SourceBundleIngestMetadataResponse: {
            /** Entry Count */
            entry_count: number;
            /**
             * Policy Version
             * @constant
             */
            policy_version: "source-bundle-v1.0";
            /** Source Entries */
            source_entries: string[];
            /** Source Entry Count */
            source_entry_count: number;
            /** Uncompressed Size */
            uncompressed_size: number;
        };
        /** SourceContextResponse */
        SourceContextResponse: {
            /** Line */
            line?: string | null;
            /** Post */
            post?: string[];
            /** Pre */
            pre?: string[];
        };
        /** SymbolBatchReprocessRequest */
        SymbolBatchReprocessRequest: {
            /** Build Id */
            build_id?: string | null;
            /** Module Id */
            module_id?: string | null;
            /** Occurrence Ids */
            occurrence_ids?: string[];
        };
        /** SymbolHealthResponse */
        SymbolHealthResponse: {
            /** Affected Occurrence Count */
            affected_occurrence_count: number;
            /** Build Id */
            build_id: string | null;
            /** Code File */
            code_file: string | null;
            /** Code Id */
            code_id: string | null;
            /** Debug File */
            debug_file: string | null;
            /** Debug Id */
            debug_id: string | null;
            /** First Seen */
            first_seen: string;
            /** Last Seen */
            last_seen: string;
            /** Module Id */
            module_id: string | null;
            /** Occurrence Ids */
            occurrence_ids: string[];
            /**
             * Status
             * @enum {string}
             */
            status: "matched" | "missing" | "mismatch";
        };
        /** UploadComplete */
        UploadComplete: {
            /** Etag */
            etag?: string | null;
            /** Multipart Upload Id */
            multipart_upload_id?: string | null;
            /** Parts */
            parts?: components["schemas"]["MultipartPart"][];
        };
        /** UploadCompletionResponse */
        UploadCompletionResponse: {
            /** Artifact Blob Id */
            artifact_blob_id?: string | null;
            /** Blob Id */
            blob_id?: string | null;
            /** Delivery */
            delivery?: ("uploaded" | "reused" | "backfilled") | null;
            /** Duplicate */
            duplicate?: boolean | null;
            /** Occurrence Id */
            occurrence_id?: string | null;
            /** Rejection Reason */
            rejection_reason?: string | null;
            /** Sha256 */
            sha256?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "INITIALIZED" | "UPLOADING" | "UPLOADED" | "VERIFYING" | "ACCEPTED" | "QUARANTINED" | "REJECTED";
            /** Upload Id */
            upload_id: string;
            /**
             * Verification Status
             * @enum {string}
             */
            verification_status: "INITIALIZED" | "UPLOADING" | "UPLOADED" | "VERIFYING" | "ACCEPTED" | "QUARANTINED" | "REJECTED";
        };
        /** UploadInitResponse */
        UploadInitResponse: {
            /** Expires In */
            expires_in: number;
            /** Headers */
            headers: {
                [key: string]: string;
            };
            /**
             * Method
             * @enum {string}
             */
            method: "PUT" | "POST";
            multipart?: components["schemas"]["PresignedMultipartResponse"] | null;
            /** Upload Id */
            upload_id: string;
            /** Url */
            url: string;
        };
        /** VersionCountResponse */
        VersionCountResponse: {
            /** Count */
            count: number;
            /** Version */
            version: string | null;
        };
        /** WorkspaceCreate */
        WorkspaceCreate: {
            /** Display Name */
            display_name?: string | null;
            /** Name */
            name: string;
            /**
             * Retention Days
             * @default 180
             */
            retention_days: number;
        };
        /** WorkspaceResponse */
        WorkspaceResponse: {
            /** Created At */
            created_at: string;
            /**
             * Default Architecture
             * @constant
             */
            default_architecture: "x86_64";
            /** Display Name */
            display_name: string | null;
            /** Id */
            id: string;
            /** In App Rule Version */
            in_app_rule_version: number;
            in_app_rules: components["schemas"]["InAppRulesBodyResponse"];
            /** Name */
            name: string;
            /**
             * Platform
             * @constant
             */
            platform: "windows";
            /** Retention Days */
            retention_days: number;
            /** Symbol Inventory Version */
            symbol_inventory_version: number;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    retry_analysis_dispatch_api_v1_analysis_runs__run_id__retry_dispatch_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RetryDispatchResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    artifact_producer_matrix_api_v1_artifact_producers_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactProducerResponse"][];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    download_artifact_api_v1_artifacts__artifact_id__download_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PresignedDownloadResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    get_build_publication_api_v1_build_publications__publication_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                publication_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BuildPublicationStatusResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    get_build_api_v1_builds__build_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                build_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BuildResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    init_artifact_delivery_v2_api_v1_builds__build_id__artifacts_deliveries_v2_init_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                build_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ArtifactDeliveryV2Init"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactDeliveryV2UploadResponse"] | components["schemas"]["ArtifactDeliveryWaitResponse"] | components["schemas"]["ArtifactDeliveryReusedResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    init_artifact_delivery_api_v1_builds__build_id__artifacts_deliveries_init_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                build_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ArtifactDeliveryInit"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactDeliveryUploadResponse"] | components["schemas"]["ArtifactDeliveryWaitResponse"] | components["schemas"]["ArtifactDeliveryReusedResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    init_artifact_upload_api_v1_builds__build_id__artifacts_uploads_init_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                build_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ArtifactUploadInit"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UploadInitResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    build_ci_status_api_v1_builds__build_id__ci_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                build_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BuildCiStatusResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    put_manifest_api_v1_builds__build_id__manifest_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                build_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": {
                    [key: string]: unknown;
                };
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BuildResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    get_build_publication_status_api_v1_builds__build_id__publication_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                build_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BuildPublicationStatusResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    list_artifacts_api_v1_builds__build_id__symbols_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                build_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactResponse"][];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    ci_producer_matrix_api_v1_ci_producers_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProducerResponse"][];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    get_group_api_v1_groups__group_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupDetailResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    patch_group_api_v1_groups__group_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GroupPatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupDetailResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    unsupported_group_edit_api_v1_groups__group_id__merge_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    unsupported_group_edit_api_v1_groups__group_id__split_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    get_occurrence_api_v1_occurrences__occurrence_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                occurrence_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OccurrenceResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    get_analysis_api_v1_occurrences__occurrence_id__analysis_get: {
        parameters: {
            query?: {
                run_id?: string | null;
            };
            header?: never;
            path: {
                occurrence_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Stable Canonical Analysis Result v1.0 */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CanonicalAnalysisResult"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    download_dump_api_v1_occurrences__occurrence_id__download_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                occurrence_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PresignedDownloadResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    occurrence_events_api_v1_occurrences__occurrence_id__events_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                occurrence_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Analysis progress Server-Sent Events stream */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/event-stream": string;
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    get_modules_api_v1_occurrences__occurrence_id__modules_get: {
        parameters: {
            query?: {
                run_id?: string | null;
            };
            header?: never;
            path: {
                occurrence_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Modules from the selected stable Canonical Analysis Result */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CanonicalModule"][];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    reprocess_api_v1_occurrences__occurrence_id__reprocess_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                occurrence_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReprocessRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReprocessResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    get_threads_api_v1_occurrences__occurrence_id__threads_get: {
        parameters: {
            query?: {
                run_id?: string | null;
            };
            header?: never;
            path: {
                occurrence_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Threads from the selected stable Canonical Analysis Result */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CanonicalThread"][];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    patch_occurrence_time_api_v1_occurrences__occurrence_id__time_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                occurrence_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OccurrenceTimePatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OccurrenceResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    get_upload_api_v1_uploads__upload_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                upload_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UploadCompletionResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    finish_upload_api_v1_uploads__upload_id__complete_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                upload_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["UploadComplete"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UploadCompletionResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    list_workspaces_api_v1_workspaces_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceResponse"][];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    create_workspace_api_v1_workspaces_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkspaceCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    get_workspace_api_v1_workspaces__workspace_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    create_build_publication_api_v1_workspaces__workspace_id__build_publications_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BuildPublicationCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BuildPublicationStatusResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    list_builds_api_v1_workspaces__workspace_id__builds_get: {
        parameters: {
            query?: {
                version?: string | null;
                producer?: string | null;
                producer_build_id?: string | null;
                cursor?: string | null;
                limit?: number;
            };
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BuildResponse"][];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    create_build_api_v1_workspaces__workspace_id__builds_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BuildCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BuildResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    init_dump_upload_api_v1_workspaces__workspace_id__dumps_uploads_init_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DumpUploadInit"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UploadInitResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    list_groups_api_v1_workspaces__workspace_id__groups_get: {
        parameters: {
            query?: {
                status?: string | null;
                group_type?: string | null;
                q?: string | null;
                cursor?: string | null;
            };
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupSummaryResponse"][];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    get_in_app_rules_api_v1_workspaces__workspace_id__in_app_rules_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InAppRulesResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    update_in_app_rules_api_v1_workspaces__workspace_id__in_app_rules_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InAppRulesUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InAppRulesUpdateResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    workspace_overview_api_v1_workspaces__workspace_id__overview_get: {
        parameters: {
            query?: {
                from?: string | null;
                to?: string | null;
            };
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OverviewResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    symbol_health_api_v1_workspaces__workspace_id__symbols_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SymbolHealthResponse"][];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    missing_symbols_api_v1_workspaces__workspace_id__symbols_missing_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SymbolHealthResponse"][];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    reindex_symbols_api_v1_workspaces__workspace_id__symbols_reindex_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["Body_reindex_symbols_api_v1_workspaces__workspace_id__symbols_reindex_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueuedTaskResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
    batch_reprocess_symbols_api_v1_workspaces__workspace_id__symbols_reprocess_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SymbolBatchReprocessRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BatchReprocessResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            410: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
            /** @description Crash-Cap error envelope */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelopeResponse"];
                };
            };
        };
    };
}
