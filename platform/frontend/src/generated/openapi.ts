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
    "/api/v1/platform/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Platform Overview */
        get: operations["platform_overview_api_v1_platform_overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
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
    "/api/v1/workspaces/{workspace_id}/occurrences": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Occurrences */
        get: operations["list_occurrences_api_v1_workspaces__workspace_id__occurrences_get"];
        put?: never;
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
    "/api/v2/capabilities": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Capabilities */
        get: operations["capabilities_api_v2_capabilities_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/occurrences/{occurrence_id}/analysis": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Analysis */
        get: operations["get_analysis_api_v2_occurrences__occurrence_id__analysis_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/occurrences/{occurrence_id}/modules": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Modules */
        get: operations["get_modules_api_v2_occurrences__occurrence_id__modules_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/occurrences/{occurrence_id}/threads": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Threads */
        get: operations["get_threads_api_v2_occurrences__occurrence_id__threads_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/runs/{run_id}/analysis": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Run Analysis */
        get: operations["get_run_analysis_api_v2_runs__run_id__analysis_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/symbol-catalog/pairs/{pair_id}/origins": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Pair Origins */
        get: operations["get_pair_origins_api_v2_symbol_catalog_pairs__pair_id__origins_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/symbol-catalog/pairs/{pair_id}/reviews": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Pair Reviews */
        get: operations["list_pair_reviews_api_v2_symbol_catalog_pairs__pair_id__reviews_get"];
        put?: never;
        /** Submit Pair Review */
        post: operations["submit_pair_review_api_v2_symbol_catalog_pairs__pair_id__reviews_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/symbol-catalog/pairs/{pair_id}/reviews/{review_id}/evidence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Review Evidence */
        get: operations["get_review_evidence_api_v2_symbol_catalog_pairs__pair_id__reviews__review_id__evidence_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/symbol-imports": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Post Import */
        post: operations["post_import_api_v2_symbol_imports_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/symbol-imports/{import_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Import */
        get: operations["get_import_api_v2_symbol_imports__import_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/symbol-imports/{import_id}/items/{item_id}/complete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Post Complete */
        post: operations["post_complete_api_v2_symbol_imports__import_id__items__item_id__complete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/symbol-imports/{import_id}/items/{item_id}/files/{kind}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Put File */
        put: operations["put_file_api_v2_symbol_imports__import_id__items__item_id__files__kind__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/workspaces/{workspace_id}/module-roles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Post Module Role */
        post: operations["post_module_role_api_v2_workspaces__workspace_id__module_roles_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-demand": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Analysis Demand */
        get: operations["get_analysis_demand_api_v2_workspaces__workspace_id__occurrences__occurrence_id__analysis_demand_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-demand/restarts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Restart Analysis Demand */
        post: operations["restart_analysis_demand_api_v2_workspaces__workspace_id__occurrences__occurrence_id__analysis_demand_restarts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Analysis History */
        get: operations["list_analysis_history_api_v2_workspaces__workspace_id__occurrences__occurrence_id__analysis_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-history/{run_id}/differences": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Analysis Differences */
        get: operations["get_analysis_differences_api_v2_workspaces__workspace_id__occurrences__occurrence_id__analysis_history__run_id__differences_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/result-reviews": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Result Reviews */
        get: operations["list_result_reviews_api_v2_workspaces__workspace_id__occurrences__occurrence_id__result_reviews_get"];
        put?: never;
        /** Submit Result Review */
        post: operations["submit_result_review_api_v2_workspaces__workspace_id__occurrences__occurrence_id__result_reviews_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/result-reviews/{review_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Result Review */
        get: operations["get_result_review_api_v2_workspaces__workspace_id__occurrences__occurrence_id__result_reviews__review_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/result-reviews/{review_id}/evidence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Result Review Evidence */
        get: operations["get_result_review_evidence_api_v2_workspaces__workspace_id__occurrences__occurrence_id__result_reviews__review_id__evidence_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/submissions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Submissions */
        get: operations["list_submissions_api_v2_workspaces__workspace_id__occurrences__occurrence_id__submissions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/workspaces/{workspace_id}/uploads": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Initialize Submission */
        post: operations["initialize_submission_api_v2_workspaces__workspace_id__uploads_post"];
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
        /** AnalysisHistoryEntry */
        AnalysisHistoryEntry: {
            /** Error Code */
            error_code: string | null;
            /** Finished At */
            finished_at: string | null;
            /** Id */
            id: string;
            /** Report Available */
            report_available: boolean;
            /** Schema Version */
            schema_version: string;
            selection: components["schemas"]["HistoryDecision"] | null;
            /** Started At */
            started_at: string | null;
            /** Status */
            status: string;
        };
        /** AnalysisHistoryPage */
        AnalysisHistoryPage: {
            /** Current Run Id */
            current_run_id: string | null;
            /** Items */
            items: components["schemas"]["AnalysisHistoryEntry"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
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
         * Crash-Cap Canonical Analysis Result v1.1 release candidate
         * @description Draft 1.1: Core-owned frozen symbol evidence. Historical 1.0 remains unchanged.
         */
        Canonical11AnalysisResult: {
            /** @description Immutable analysis run id. */
            analysis_id: string;
            build_resolution: components["schemas"]["Canonical11BuildResolution"];
            crash: {
                /** @enum {string|null} */
                access_type?: "read" | "write" | "execute" | "readwrite" | null;
                address?: components["schemas"]["Canonical11HexAddr"];
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
                dump_timestamp?: components["schemas"]["Canonical11NullableTimestamp"];
                /** @enum {string} */
                kind: "user_minidump" | "kernel" | "unknown_binary";
                /** Format: date-time */
                occurred_at: string;
                reported_at?: components["schemas"]["Canonical11NullableTimestamp"];
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
            modules: components["schemas"]["Canonical11Module"][];
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
                warnings: components["schemas"]["Canonical11QualityWarning"][];
            };
            /** @constant */
            schema_version: "1.1";
            symbol_resolution: {
                context_sha256: string;
                inspect_sha256: string;
                manifest: {
                    object_key: string;
                    sha256: string;
                };
                resolution_evidence_fingerprint: string;
                /** @constant */
                selection_version: "pair-selection-v1";
            };
            threads: components["schemas"]["Canonical11Thread"][];
            workspace_id: string;
        } & unknown;
        Canonical11BuildResolution: {
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
        Canonical11Frame: {
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
            module_index: number | null;
            physical_frame_index: number;
            relative_addr?: components["schemas"]["Canonical11HexAddr"];
            /** @description Reserved. Phase 1 omits or sets null. */
            source_context?: {
                line?: string;
                post?: string[];
                pre?: string[];
            } | null;
            trust: components["schemas"]["Canonical11Trust"];
            /** @enum {unknown} */
            unwind_method: "context" | "call_frame_info" | "cfi_scan" | "frame_pointer" | "scan" | "prewalked" | "unknown";
        };
        Canonical11HexAddr: string | null;
        Canonical11Module: {
            artifact_ids: string[];
            code_file: string;
            code_id?: string | null;
            debug_file?: string | null;
            debug_id?: string | null;
            image_base?: components["schemas"]["Canonical11HexAddr"];
            image_size?: number | null;
            in_app: boolean;
            module_index: number;
            role: components["schemas"]["Canonical11ModuleRole"];
            selection: {
                candidate_evidence: {
                    object_key: string;
                    sha256: string;
                };
                candidate_pair_ids: string[];
                candidates_complete: boolean;
                identity: {
                    /** @enum {unknown} */
                    architecture: "x86_64" | "x86" | "arm64" | "unknown";
                    code_id: string | null;
                    debug_id: string | null;
                };
                module_index: number;
                /** @enum {unknown} */
                reason: "missing" | "unique" | "identity_conflict" | "withdrawn" | "location_unavailable" | "incomplete_identity" | "enumeration_failed" | "validation_incomplete";
                review_refs: string[];
                selected_pair_id: string | null;
                /** @enum {unknown} */
                state: "none" | "unique" | "conflict" | "unavailable" | "indeterminate";
                unavailable_pair_ids: string[];
            } & (unknown & unknown & unknown & unknown);
            source_outcomes: {
                diagnostic_ref: {
                    object_key: string;
                    sha256: string;
                } | null;
                /** @enum {unknown} */
                failure_class: "none" | "transient" | "permanent" | "unknown";
                /** @enum {unknown} */
                outcome: "found" | "missing" | "failed" | "blocked" | "unknown";
                reason: string;
                source_id: string;
                /** @enum {unknown} */
                stage: "download_pe" | "download_pdb" | "unwind" | "symbolicate";
            }[];
            /** @enum {string} */
            status: "matched" | "missing_pe" | "missing_pdb" | "pdb_mismatch" | "pe_mismatch" | "corrupted" | "system_symbol_pending" | "unsupported" | "symbol_conflict" | "symbol_unavailable" | "symbol_indeterminate";
        };
        /** @enum {string} */
        Canonical11ModuleRole: "entrypoint" | "owned" | "dependency" | "system" | "unknown";
        /** Format: date-time */
        Canonical11NullableTimestamp: string | null;
        Canonical11QualityWarning: {
            /** @enum {string} */
            code: "missing_pe" | "missing_pdb" | "pdb_mismatch" | "pe_mismatch" | "missing_pe_unwind" | "system_symbol_pending" | "system_symbol_failed" | "symbolicator_failed" | "truncated_dump" | "scan_frames" | "module_limit_truncated" | "unsupported_inline" | "ambiguous_build" | "unresolved_build" | "unknown_crash_type" | "unclassified_exact" | "other" | "symbol_conflict" | "symbol_unavailable" | "symbol_indeterminate";
            debug_id?: string | null;
            message: string;
            module?: string | null;
        };
        Canonical11Thread: {
            frames: components["schemas"]["Canonical11Frame"][];
            id: number;
            is_crashing: boolean;
            name?: string | null;
        };
        /** @enum {string} */
        Canonical11Trust: "context" | "cfi" | "frame_pointer" | "scan" | "unknown";
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
        /** CapabilitiesResponse */
        CapabilitiesResponse: {
            /** Enabled Writes */
            enabled_writes: string[];
            /** Pause Reason */
            pause_reason: string | null;
            /** Reader Versions */
            reader_versions: string[];
        };
        /** CatalogOriginView */
        CatalogOriginView: {
            /** Build Id */
            build_id: string | null;
            /** Id */
            id: string;
            /** Import Id */
            import_id?: string | null;
            /** Origin Key */
            origin_key: string;
            /**
             * Origin Type
             * @enum {string}
             */
            origin_type: "import_item" | "build_artifacts" | "publication";
            /** Source Label */
            source_label?: string | null;
            /** Source Workspace Id */
            source_workspace_id: string | null;
        };
        /** CatalogPairOrigins */
        CatalogPairOrigins: {
            /** Architecture */
            architecture: string;
            /** Code Id */
            code_id: string;
            /** Debug Id */
            debug_id: string;
            /** Items */
            items: components["schemas"]["CatalogOriginView"][];
            /** Next Cursor */
            next_cursor: string | null;
            /** Pair Id */
            pair_id: string;
            /** Qualification Version */
            qualification_version: number;
            /**
             * State
             * @enum {string}
             */
            state: "active" | "withdrawn";
        };
        /** CatalogReviewEvidence */
        CatalogReviewEvidence: {
            /** Evidence */
            evidence: string;
            /** Expected Version */
            expected_version: number;
            /** Pair Id */
            pair_id: string;
            /** Reason */
            reason: string;
            /** Reviewer */
            reviewer: string;
            /**
             * Schema Version
             * @constant
             */
            schema_version: "catalog-provider-review-v1";
            /**
             * State
             * @enum {string}
             */
            state: "active" | "withdrawn";
        };
        /** CatalogReviewPage */
        CatalogReviewPage: {
            /** Items */
            items: components["schemas"]["CatalogReviewResponse"][];
            /** Next Version */
            next_version: number | null;
        };
        /** CatalogReviewRequest */
        CatalogReviewRequest: {
            /** Evidence */
            evidence: string;
            /** Expected Version */
            expected_version: number;
            /** Idempotency Key */
            idempotency_key: string;
            /** Reason */
            reason: string;
            /** Reviewer */
            reviewer: string;
            /**
             * State
             * @enum {string}
             */
            state: "active" | "withdrawn";
        };
        /** CatalogReviewResponse */
        CatalogReviewResponse: {
            /** Evidence Sha256 */
            evidence_sha256: string;
            /** Id */
            id: string;
            /** Pair Id */
            pair_id: string;
            /** Qualification Version */
            qualification_version: number;
            /** Reason */
            reason: string;
            /**
             * State
             * @enum {string}
             */
            state: "active" | "withdrawn";
        };
        /** DemandRestartRequest */
        DemandRestartRequest: {
            /** Expected Generation */
            expected_generation: number;
            /** Expected Sequence */
            expected_sequence: number;
            /** Idempotency Key */
            idempotency_key: string;
            /** Rationale */
            rationale: string;
        };
        /** DemandRestartResponse */
        DemandRestartResponse: {
            /** Change Sequence */
            change_sequence: number;
            /** Demand Id */
            demand_id: string;
            /** Generation */
            generation: number;
            /** Occurrence Id */
            occurrence_id: string;
            /** Restart Id */
            restart_id: string;
            /**
             * State
             * @constant
             */
            state: "preparing";
        };
        /** DemandStatusResponse */
        DemandStatusResponse: {
            /**
             * Change Sequence
             * @default 0
             */
            change_sequence: number;
            /** Current Run Id */
            current_run_id?: string | null;
            /** Demand Id */
            demand_id: string;
            /** Generation */
            generation: number;
            /** Not Before */
            not_before: string | null;
            /** Occurrence Id */
            occurrence_id: string;
            /** Reason */
            reason: string | null;
            /** Retry Attempt */
            retry_attempt: number;
            /** Run Id */
            run_id: string | null;
            /**
             * State
             * @enum {string}
             */
            state: "preparing" | "coalescing" | "queued" | "running" | "updated" | "retained" | "needs_review" | "retry_wait" | "retry_exhausted" | "cannot_recompute" | "paused";
            /** Withdrawn Basis Pair Ids */
            withdrawn_basis_pair_ids?: string[] | null;
        };
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
        /** EvidenceDifference */
        EvidenceDifference: {
            after: components["schemas"]["JsonValue"];
            before: components["schemas"]["JsonValue"];
            /** Path */
            path: string;
        };
        /** EvidenceDifferencePage */
        EvidenceDifferencePage: {
            /** Candidate Run Id */
            candidate_run_id: string;
            /** Items */
            items: components["schemas"]["EvidenceDifference"][];
            /** Next Offset */
            next_offset: number | null;
            selection: components["schemas"]["HistoryDecision"];
            /** Total */
            total: number;
        };
        /** FileResult */
        FileResult: {
            /**
             * State
             * @default uploaded
             * @constant
             */
            state: "uploaded";
            /** Upload Id */
            upload_id: string;
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
        /** HistoryDecision */
        HistoryDecision: {
            /**
             * Decision
             * @enum {string}
             */
            decision: "promote" | "retain" | "incomparable" | "correct";
            /** Observed Current Run Id */
            observed_current_run_id: string | null;
            /** Reason */
            reason: string;
            /** Retry Recommended */
            retry_recommended: boolean;
            /** Rule Version */
            rule_version: string;
        };
        /** ImportFileClaim */
        ImportFileClaim: {
            /** Name */
            name: string;
            /** Raw Sha256 */
            raw_sha256: string;
            /** Raw Size */
            raw_size: number;
        };
        /** ImportItemResult */
        ImportItemResult: {
            /** Client Pair Id */
            client_pair_id: string;
            /** Error Code */
            error_code: string | null;
            /** Item Id */
            item_id: string;
            /** Pair Id */
            pair_id: string | null;
            /** Pdb Upload Id */
            pdb_upload_id: string;
            /** Pe Upload Id */
            pe_upload_id: string;
            /**
             * State
             * @enum {string}
             */
            state: "staging" | "queued" | "verifying" | "available" | "rejected" | "retry_exhausted";
        };
        /** ImportPairClaim */
        ImportPairClaim: {
            /** Client Pair Id */
            client_pair_id: string;
            pdb: components["schemas"]["ImportFileClaim"];
            pe: components["schemas"]["ImportFileClaim"];
        };
        /** ImportRequest */
        ImportRequest: {
            /** Idempotency Key */
            idempotency_key: string;
            /** Pairs */
            pairs: components["schemas"]["ImportPairClaim"][];
            /** Source Label */
            source_label: string;
        };
        /** ImportResult */
        ImportResult: {
            /** Import Id */
            import_id: string;
            /** Items */
            items: components["schemas"]["ImportItemResult"][];
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
        JsonValue: unknown;
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
        /** ModuleIdentity */
        ModuleIdentity: {
            /**
             * Architecture
             * @constant
             */
            architecture: "x86_64";
            /** Code Id */
            code_id: string;
            /** Debug Id */
            debug_id: string;
        };
        /** ModuleRoleRequest */
        ModuleRoleRequest: {
            identity: components["schemas"]["ModuleIdentity"];
            /**
             * Role
             * @enum {string}
             */
            role: "owned" | "dependency";
        };
        /** ModuleRoleResponse */
        ModuleRoleResponse: {
            /** Changed */
            changed: boolean;
            /** Fanout Attempt Id */
            fanout_attempt_id: string | null;
            identity: components["schemas"]["ModuleIdentity"];
            /**
             * Role
             * @enum {string}
             */
            role: "owned" | "dependency";
            /** Version */
            version: number;
            /** Workspace Id */
            workspace_id: string;
        };
        /** MultipartPart */
        MultipartPart: {
            /** Etag */
            etag: string;
            /** Part Number */
            part_number: number;
        };
        /** OccurrenceListItemResponse */
        OccurrenceListItemResponse: {
            current_analysis: components["schemas"]["AnalysisRunResponse"] | null;
            group: components["schemas"]["GroupSummaryResponse"] | null;
            /** Id */
            id: string;
            latest_attempt: components["schemas"]["AnalysisRunResponse"] | null;
            /** Occurred At */
            occurred_at: string;
            summary: components["schemas"]["OccurrenceListSummaryResponse"] | null;
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
        /** OccurrenceListPageResponse */
        OccurrenceListPageResponse: {
            /** Items */
            items: components["schemas"]["OccurrenceListItemResponse"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /** OccurrenceListSummaryResponse */
        OccurrenceListSummaryResponse: {
            /** Access Type */
            access_type: string | null;
            /**
             * Crash Type
             * @enum {string}
             */
            crash_type: "crash" | "hang" | "unknown";
            /** Exception Code */
            exception_code: string | null;
            /** Exception Name */
            exception_name: string | null;
            /** Fault Module */
            fault_module: string | null;
            /** Top Function */
            top_function: string | null;
            /** Version */
            version: string | null;
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
        /** PlatformAttentionResponse */
        PlatformAttentionResponse: {
            /** In Progress */
            in_progress: number;
            /** Latest Attempt Failed */
            latest_attempt_failed: number;
            /** Symbol Affected Occurrences */
            symbol_affected_occurrences: number;
            /** Unclassified Crashes */
            unclassified_crashes: number;
        };
        /** PlatformOverviewResponse */
        PlatformOverviewResponse: {
            attention: components["schemas"]["PlatformAttentionResponse"];
            /** Recent Occurrences */
            recent_occurrences: components["schemas"]["OccurrenceListItemResponse"][];
            /** Window End */
            window_end: string;
            /** Window Start */
            window_start: string;
            /** Workspace Count */
            workspace_count: number;
            /** Workspaces */
            workspaces: components["schemas"]["PlatformWorkspaceSummaryResponse"][];
        };
        /** PlatformWorkspaceSummaryResponse */
        PlatformWorkspaceSummaryResponse: {
            /** Attention Count */
            attention_count: number;
            /** Last Occurrence At */
            last_occurrence_at: string | null;
            /** Occurrence Count */
            occurrence_count: number;
            workspace: components["schemas"]["WorkspaceResponse"];
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
        /** ProviderBasisView */
        ProviderBasisView: {
            /** Object Key */
            object_key: string;
            /** Pair Id */
            pair_id: string;
            /** Qualification Version */
            qualification_version: number;
            /** Reason */
            reason: string;
            /** Review Id */
            review_id: string;
            /** Sha256 */
            sha256: string;
            /**
             * State
             * @enum {string}
             */
            state: "active" | "withdrawn";
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
        /** ResultReviewAudit */
        ResultReviewAudit: {
            /** Candidate Evidence */
            candidate_evidence: {
                [key: string]: components["schemas"]["JsonValue"];
            };
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Current Evidence */
            current_evidence: {
                [key: string]: components["schemas"]["JsonValue"];
            };
            /** Occurrence Id */
            occurrence_id: string;
            /** Provider Basis */
            provider_basis: components["schemas"]["ProviderBasisView"][];
            request: components["schemas"]["ResultReviewRequest"];
            /** Request Sha256 */
            request_sha256: string;
            /** Review Id */
            review_id: string;
            /**
             * Schema Version
             * @constant
             */
            schema_version: "result-review-audit-v1";
        };
        /** ResultReviewPage */
        ResultReviewPage: {
            /** Items */
            items: components["schemas"]["ResultReviewResponse"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /** ResultReviewRequest */
        ResultReviewRequest: {
            /** Basis Reviews */
            basis_reviews: components["schemas"]["ReviewBasisReference"][];
            /** Candidate Canonical Sha256 */
            candidate_canonical_sha256: string;
            /** Candidate Run Id */
            candidate_run_id: string;
            /**
             * Cause
             * @enum {string}
             */
            cause: "engine_upgrade" | "role_change" | "evidence_correction";
            /** Current Canonical Sha256 */
            current_canonical_sha256: string;
            /** Current Run Id */
            current_run_id: string;
            /** Idempotency Key */
            idempotency_key: string;
            /** Rationale */
            rationale: string;
            /** Reviewed By */
            reviewed_by: string;
            /**
             * Schema Version
             * @constant
             */
            schema_version: "result-review-request-v1";
        };
        /** ResultReviewResponse */
        ResultReviewResponse: {
            /** Audit Sha256 */
            audit_sha256: string;
            /** Candidate Run Id */
            candidate_run_id: string;
            /**
             * Cause
             * @enum {string}
             */
            cause: "engine_upgrade" | "role_change" | "evidence_correction";
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Current Run Id */
            current_run_id: string;
            /**
             * Decision
             * @enum {string}
             */
            decision: "promote" | "retain" | "incomparable" | "correct";
            /** Id */
            id: string;
            /** Occurrence Id */
            occurrence_id: string;
            /** Reason */
            reason: string;
            request: components["schemas"]["ResultReviewRequest"];
            /** Request Sha256 */
            request_sha256: string;
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
        /** ReviewBasisReference */
        ReviewBasisReference: {
            /** Evidence Sha256 */
            evidence_sha256: string;
            /** Review Id */
            review_id: string;
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
        /** SubmissionPage */
        SubmissionPage: {
            /** Items */
            items: components["schemas"]["SubmissionResponse"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /** SubmissionResponse */
        SubmissionResponse: {
            /** Batch */
            batch: string | null;
            /** Filename */
            filename: string;
            /** Label */
            label: string | null;
            /** Source */
            source: string;
            /**
             * Submitted At
             * Format: date-time
             */
            submitted_at: string;
            /** Upload Id */
            upload_id: string;
            /**
             * Verified At
             * Format: date-time
             */
            verified_at: string;
        };
        /** SubmissionUploadInit */
        SubmissionUploadInit: {
            /** Batch */
            batch?: string | null;
            /** Capture Profile */
            capture_profile?: ("light-crash" | "rich-crash" | "hang" | "full-memory") | null;
            /** Filename */
            filename: string;
            /** Label */
            label?: string | null;
            /** Reported At */
            reported_at?: string | null;
            /** Reported Build Id */
            reported_build_id?: string | null;
            /** Sha256 */
            sha256?: string | null;
            /** Size */
            size: number;
            /** Source */
            source: string;
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
    platform_overview_api_v1_platform_overview_get: {
        parameters: {
            query?: {
                from?: string | null;
                to?: string | null;
            };
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
                    "application/json": components["schemas"]["PlatformOverviewResponse"];
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
    list_occurrences_api_v1_workspaces__workspace_id__occurrences_get: {
        parameters: {
            query?: {
                from?: string | null;
                to?: string | null;
                crash_type?: ("crash" | "hang" | "unknown" | "no_current") | null;
                latest_status?: ("UPLOADED" | "VALIDATING" | "INSPECTED" | "MATCHING_SYMBOLS" | "WAITING_FOR_SYMBOLS" | "SYMBOLS_READY" | "QUEUED" | "ANALYZING" | "NORMALIZING" | "GROUPING" | "COMPLETE" | "PARTIAL" | "FAILED" | "REJECTED" | "CANCELLED" | "TIMEOUT" | "OOM") | null;
                resolution_method?: ("reported" | "auto_unique" | "manual" | "ambiguous" | "unresolved" | "no_current") | null;
                version?: string | null;
                test_label?: string | null;
                test_batch?: string | null;
                build_id?: string | null;
                grouping?: ("exact" | "unclassified" | "no_current") | null;
                q?: string | null;
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
                    "application/json": components["schemas"]["OccurrenceListPageResponse"];
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
    capabilities_api_v2_capabilities_get: {
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
                    "application/json": components["schemas"]["CapabilitiesResponse"];
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
    get_analysis_api_v2_occurrences__occurrence_id__analysis_get: {
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
            /** @description Original immutable Canonical 1.0 or 1.1 bytes */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CanonicalAnalysisResult"] | components["schemas"]["Canonical11AnalysisResult"];
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
    get_modules_api_v2_occurrences__occurrence_id__modules_get: {
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
            /** @description Selected Canonical section (1.0 or 1.1) */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": (components["schemas"]["CanonicalModule"] | components["schemas"]["Canonical11Module"])[];
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
    get_threads_api_v2_occurrences__occurrence_id__threads_get: {
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
            /** @description Selected Canonical section (1.0 or 1.1) */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": (components["schemas"]["CanonicalThread"] | components["schemas"]["Canonical11Thread"])[];
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
    get_run_analysis_api_v2_runs__run_id__analysis_get: {
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
            /** @description Original immutable Canonical 1.0 or 1.1 bytes */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CanonicalAnalysisResult"] | components["schemas"]["Canonical11AnalysisResult"];
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
    get_pair_origins_api_v2_symbol_catalog_pairs__pair_id__origins_get: {
        parameters: {
            query?: {
                cursor?: string | null;
                limit?: number;
            };
            header?: never;
            path: {
                pair_id: string;
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
                    "application/json": components["schemas"]["CatalogPairOrigins"];
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
    list_pair_reviews_api_v2_symbol_catalog_pairs__pair_id__reviews_get: {
        parameters: {
            query?: {
                before_version?: number | null;
                limit?: number;
            };
            header?: never;
            path: {
                pair_id: string;
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
                    "application/json": components["schemas"]["CatalogReviewPage"];
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
    submit_pair_review_api_v2_symbol_catalog_pairs__pair_id__reviews_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pair_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CatalogReviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CatalogReviewResponse"];
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
    get_review_evidence_api_v2_symbol_catalog_pairs__pair_id__reviews__review_id__evidence_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pair_id: string;
                review_id: string;
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
                    "application/json": components["schemas"]["CatalogReviewEvidence"];
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
    post_import_api_v2_symbol_imports_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ImportRequest"];
            };
        };
        responses: {
            /** @description OK */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportResult"];
                };
            };
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportResult"];
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
    get_import_api_v2_symbol_imports__import_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                import_id: string;
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
                    "application/json": components["schemas"]["ImportResult"];
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
    post_complete_api_v2_symbol_imports__import_id__items__item_id__complete_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                import_id: string;
                item_id: string;
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
                    "application/json": components["schemas"]["ImportResult"];
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
    put_file_api_v2_symbol_imports__import_id__items__item_id__files__kind__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                import_id: string;
                item_id: string;
                kind: "pe" | "pdb";
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/octet-stream": string;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FileResult"];
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
    post_module_role_api_v2_workspaces__workspace_id__module_roles_post: {
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
                "application/json": components["schemas"]["ModuleRoleRequest"];
            };
        };
        responses: {
            /** @description OK */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModuleRoleResponse"];
                };
            };
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModuleRoleResponse"];
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
    get_analysis_demand_api_v2_workspaces__workspace_id__occurrences__occurrence_id__analysis_demand_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["DemandStatusResponse"] | null;
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
    restart_analysis_demand_api_v2_workspaces__workspace_id__occurrences__occurrence_id__analysis_demand_restarts_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                occurrence_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DemandRestartRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DemandRestartResponse"];
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
    list_analysis_history_api_v2_workspaces__workspace_id__occurrences__occurrence_id__analysis_history_get: {
        parameters: {
            query?: {
                cursor?: string | null;
                limit?: number;
            };
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["AnalysisHistoryPage"];
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
    get_analysis_differences_api_v2_workspaces__workspace_id__occurrences__occurrence_id__analysis_history__run_id__differences_get: {
        parameters: {
            query?: {
                offset?: number;
                limit?: number;
            };
            header?: never;
            path: {
                workspace_id: string;
                occurrence_id: string;
                run_id: string;
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
                    "application/json": components["schemas"]["EvidenceDifferencePage"];
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
    list_result_reviews_api_v2_workspaces__workspace_id__occurrences__occurrence_id__result_reviews_get: {
        parameters: {
            query?: {
                cursor?: string | null;
                limit?: number;
            };
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["ResultReviewPage"];
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
    submit_result_review_api_v2_workspaces__workspace_id__occurrences__occurrence_id__result_reviews_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                occurrence_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResultReviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResultReviewResponse"];
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
    get_result_review_api_v2_workspaces__workspace_id__occurrences__occurrence_id__result_reviews__review_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                occurrence_id: string;
                review_id: string;
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
                    "application/json": components["schemas"]["ResultReviewResponse"];
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
    get_result_review_evidence_api_v2_workspaces__workspace_id__occurrences__occurrence_id__result_reviews__review_id__evidence_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                occurrence_id: string;
                review_id: string;
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
                    "application/json": components["schemas"]["ResultReviewAudit"];
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
    list_submissions_api_v2_workspaces__workspace_id__occurrences__occurrence_id__submissions_get: {
        parameters: {
            query?: {
                cursor?: string | null;
                limit?: number;
            };
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["SubmissionPage"];
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
    initialize_submission_api_v2_workspaces__workspace_id__uploads_post: {
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
                "application/json": components["schemas"]["SubmissionUploadInit"];
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
}
