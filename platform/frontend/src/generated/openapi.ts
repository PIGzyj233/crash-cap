export interface paths {
    "/api/v3/artifacts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List V3 Artifacts */
        get: operations["list_v3_artifacts_api_v3_artifacts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/artifacts/{artifact_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get V3 Artifact */
        get: operations["get_v3_artifact_api_v3_artifacts__artifact_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/capabilities": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Capabilities */
        get: operations["capabilities_api_v3_capabilities_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/groups/{group_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Group */
        get: operations["get_group_api_v3_groups__group_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Patch Group */
        patch: operations["patch_group_api_v3_groups__group_id__patch"];
        trace?: never;
    };
    "/api/v3/groups/{group_id}/merge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Unsupported Group Edit */
        post: operations["unsupported_group_edit_api_v3_groups__group_id__merge_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/groups/{group_id}/split": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Unsupported Group Edit */
        post: operations["unsupported_group_edit_api_v3_groups__group_id__split_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/occurrences/{occurrence_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Occurrence */
        get: operations["get_occurrence_api_v3_occurrences__occurrence_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/occurrences/{occurrence_id}/analysis": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Analysis */
        get: operations["get_analysis_api_v3_occurrences__occurrence_id__analysis_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/occurrences/{occurrence_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download Dump */
        get: operations["download_dump_api_v3_occurrences__occurrence_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/occurrences/{occurrence_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Occurrence Events */
        get: operations["occurrence_events_api_v3_occurrences__occurrence_id__events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/occurrences/{occurrence_id}/modules": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Modules */
        get: operations["get_modules_api_v3_occurrences__occurrence_id__modules_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/occurrences/{occurrence_id}/reprocess": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reprocess */
        post: operations["reprocess_api_v3_occurrences__occurrence_id__reprocess_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/occurrences/{occurrence_id}/threads": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Threads */
        get: operations["get_threads_api_v3_occurrences__occurrence_id__threads_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/occurrences/{occurrence_id}/time": {
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
        patch: operations["patch_occurrence_time_api_v3_occurrences__occurrence_id__time_patch"];
        trace?: never;
    };
    "/api/v3/occurrences/{occurrence_id}/version": {
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
        /** Patch Occurrence Version */
        patch: operations["patch_occurrence_version_api_v3_occurrences__occurrence_id__version_patch"];
        trace?: never;
    };
    "/api/v3/platform/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Platform Overview */
        get: operations["platform_overview_api_v3_platform_overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/runs/{run_id}/analysis": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Run Analysis */
        get: operations["get_run_analysis_api_v3_runs__run_id__analysis_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/symbol-catalog/pairs/{pair_id}/origins": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Pair Origins */
        get: operations["get_pair_origins_api_v3_symbol_catalog_pairs__pair_id__origins_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/symbol-catalog/pairs/{pair_id}/reviews": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Pair Reviews */
        get: operations["list_pair_reviews_api_v3_symbol_catalog_pairs__pair_id__reviews_get"];
        put?: never;
        /** Submit Pair Review */
        post: operations["submit_pair_review_api_v3_symbol_catalog_pairs__pair_id__reviews_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/symbol-catalog/pairs/{pair_id}/reviews/{review_id}/evidence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Review Evidence */
        get: operations["get_review_evidence_api_v3_symbol_catalog_pairs__pair_id__reviews__review_id__evidence_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/uploads/{upload_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get V3 Upload */
        get: operations["get_v3_upload_api_v3_uploads__upload_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/uploads/{upload_id}:complete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Complete V3 Upload */
        post: operations["complete_v3_upload_api_v3_uploads__upload_id__complete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/uploads:init": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Initialize V3 Upload */
        post: operations["initialize_v3_upload_api_v3_uploads_init_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Workspaces */
        get: operations["list_workspaces_api_v3_workspaces_get"];
        put?: never;
        /** Create Workspace */
        post: operations["create_workspace_api_v3_workspaces_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Workspace */
        get: operations["get_workspace_api_v3_workspaces__workspace_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/groups": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Groups */
        get: operations["list_groups_api_v3_workspaces__workspace_id__groups_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/in-app-rules": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get In App Rules */
        get: operations["get_in_app_rules_api_v3_workspaces__workspace_id__in_app_rules_get"];
        /** Update In App Rules */
        put: operations["update_in_app_rules_api_v3_workspaces__workspace_id__in_app_rules_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/module-roles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Post Module Role */
        post: operations["post_module_role_api_v3_workspaces__workspace_id__module_roles_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/occurrences": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Occurrences */
        get: operations["list_occurrences_api_v3_workspaces__workspace_id__occurrences_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-demand": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Analysis Demand */
        get: operations["get_analysis_demand_api_v3_workspaces__workspace_id__occurrences__occurrence_id__analysis_demand_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-demand/restarts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Restart Analysis Demand */
        post: operations["restart_analysis_demand_api_v3_workspaces__workspace_id__occurrences__occurrence_id__analysis_demand_restarts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Analysis History */
        get: operations["list_analysis_history_api_v3_workspaces__workspace_id__occurrences__occurrence_id__analysis_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-history/{run_id}/differences": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Analysis Differences */
        get: operations["get_analysis_differences_api_v3_workspaces__workspace_id__occurrences__occurrence_id__analysis_history__run_id__differences_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/occurrences/{occurrence_id}/result-reviews": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Result Reviews */
        get: operations["list_result_reviews_api_v3_workspaces__workspace_id__occurrences__occurrence_id__result_reviews_get"];
        put?: never;
        /** Submit Result Review */
        post: operations["submit_result_review_api_v3_workspaces__workspace_id__occurrences__occurrence_id__result_reviews_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/occurrences/{occurrence_id}/result-reviews/{review_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Result Review */
        get: operations["get_result_review_api_v3_workspaces__workspace_id__occurrences__occurrence_id__result_reviews__review_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/occurrences/{occurrence_id}/result-reviews/{review_id}/evidence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Result Review Evidence */
        get: operations["get_result_review_evidence_api_v3_workspaces__workspace_id__occurrences__occurrence_id__result_reviews__review_id__evidence_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/occurrences/{occurrence_id}/submissions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Submissions */
        get: operations["list_submissions_api_v3_workspaces__workspace_id__occurrences__occurrence_id__submissions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Workspace Overview */
        get: operations["workspace_overview_api_v3_workspaces__workspace_id__overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/symbols/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Symbol Health */
        get: operations["symbol_health_api_v3_workspaces__workspace_id__symbols_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/symbols/missing": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Missing Symbols */
        get: operations["missing_symbols_api_v3_workspaces__workspace_id__symbols_missing_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v3/workspaces/{workspace_id}/symbols/reprocess": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Batch Reprocess Symbols */
        post: operations["batch_reprocess_symbols_api_v3_workspaces__workspace_id__symbols_reprocess_post"];
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
            /** Started At */
            started_at: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "UPLOADED" | "VALIDATING" | "INSPECTED" | "MATCHING_SYMBOLS" | "WAITING_FOR_SYMBOLS" | "SYMBOLS_READY" | "QUEUED" | "ANALYZING" | "NORMALIZING" | "GROUPING" | "COMPLETE" | "PARTIAL" | "FAILED" | "REJECTED" | "CANCELLED" | "TIMEOUT" | "OOM";
        };
        /** ArtifactEntryResponse */
        ArtifactEntryResponse: {
            /**
             * Availability
             * @enum {string}
             */
            availability: "validating" | "waiting_for_pair" | "symbols_available" | "identity_conflict" | "no_debug_identity" | "storage_unavailable";
            /** Code Id */
            code_id: string | null;
            /** Created At */
            created_at: string;
            /** Debug Id */
            debug_id: string | null;
            /** File Id */
            file_id: string;
            /** Id */
            id: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "pe" | "pdb";
            /** Name */
            name: string;
            /** Sha256 */
            sha256: string;
            /** Size */
            size: number;
            /**
             * Source
             * @enum {string}
             */
            source: "api" | "cli" | "browser";
            /** Version */
            version: string | null;
            /** Workspace Id */
            workspace_id: string | null;
        };
        /** ArtifactPageResponse */
        ArtifactPageResponse: {
            /** Items */
            items: components["schemas"]["ArtifactEntryResponse"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /** BatchReprocessResponse */
        BatchReprocessResponse: {
            /** Affected Occurrence Count */
            affected_occurrence_count: number;
            /** Demand Ids */
            demand_ids: string[];
            /** Occurrence Ids */
            occurrence_ids: string[];
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
        /**
         * Canonical Analysis Result 2.0
         * @description Draft 1.1: Core-owned frozen symbol evidence. Historical 1.0 remains unchanged.
         */
        CanonicalAnalysisResult: {
            /** @description Immutable analysis run id. */
            analysis_id: string;
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
            schema_version: "2.0";
            symbol_resolution: {
                context_sha256: string;
                inspect_sha256: string;
                resolution_evidence_fingerprint: string;
                selection: {
                    object_key: string;
                    sha256: string;
                };
                /** @constant */
                selection_version: "pair-selection-v1";
            };
            threads: components["schemas"]["CanonicalThread"][];
            workspace_id: string;
        } & unknown;
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
            module_index: number | null;
            physical_frame_index: number;
            relative_addr?: components["schemas"]["CanonicalHexAddr"];
            /** @description Reserved. Phase 1 omits or sets null. */
            source_context?: {
                line?: string;
                post?: string[];
                pre?: string[];
            } | null;
            trust: components["schemas"]["CanonicalTrust"];
            /** @enum {unknown} */
            unwind_method: "context" | "call_frame_info" | "cfi_scan" | "frame_pointer" | "scan" | "prewalked" | "unknown";
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
            /** Module Index */
            module_index?: number | null;
            /** Physical Frame Index */
            physical_frame_index?: number | null;
            /** Relative Addr */
            relative_addr?: string | null;
            source_context?: components["schemas"]["SourceContextResponse"] | null;
            /**
             * Trust
             * @enum {string}
             */
            trust: "context" | "cfi" | "frame_pointer" | "scan" | "unknown";
            /**
             * Unwind Method
             * @default unknown
             * @enum {string}
             */
            unwind_method: "context" | "call_frame_info" | "cfi_scan" | "frame_pointer" | "scan" | "prewalked" | "unknown";
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
            module_index: number;
            role: components["schemas"]["CanonicalModuleRole"];
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
        CanonicalModuleRole: "entrypoint" | "owned" | "dependency" | "system" | "unknown";
        /** Format: date-time */
        CanonicalNullableTimestamp: string | null;
        CanonicalQualityWarning: {
            /** @enum {string} */
            code: "missing_pe" | "missing_pdb" | "pdb_mismatch" | "pe_mismatch" | "missing_pe_unwind" | "system_symbol_pending" | "system_symbol_failed" | "symbolicator_failed" | "truncated_dump" | "scan_frames" | "module_limit_truncated" | "unsupported_inline" | "ambiguous_build" | "unresolved_build" | "unknown_crash_type" | "unclassified_exact" | "other" | "symbol_conflict" | "symbol_unavailable" | "symbol_indeterminate";
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
            /** Artifact Entry Id */
            artifact_entry_id?: string | null;
            /** Id */
            id: string;
            /** Origin Key */
            origin_key: string;
            /**
             * Origin Type
             * @constant
             */
            origin_type: "upload";
            /** Source Label */
            source_label?: string | null;
            /** Source Workspace Id */
            source_workspace_id: string | null;
            /** Version */
            version?: string | null;
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
        /** GroupDetailResponse */
        GroupDetailResponse: {
            /** Fingerprint */
            fingerprint: string;
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
            /** Version Distribution */
            version_distribution: components["schemas"]["VersionDistributionResponse"][];
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
            /** Demand Ids */
            demand_ids: string[];
            /** Exclude Modules */
            exclude_modules: string[];
            /** Include Modules */
            include_modules: string[];
            /** Version */
            version: number;
            /** Workspace Id */
            workspace_id: string;
        };
        JsonValue: unknown;
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
            /** Version */
            version: string | null;
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
            /**
             * Time Source
             * @enum {string}
             */
            time_source: "dump" | "reported" | "uploaded" | "manual";
            /** Uploaded At */
            uploaded_at: string;
            /** Version */
            version: string | null;
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
        /** OccurrenceVersionPatch */
        OccurrenceVersionPatch: {
            /** Version */
            version?: string | null;
        };
        /** OccurrenceVersionResponse */
        OccurrenceVersionResponse: {
            /** Occurrence Id */
            occurrence_id: string;
            /** Updated At */
            updated_at: string;
            /** Version */
            version: string | null;
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
        /** ReprocessResponse */
        ReprocessResponse: {
            /** Created */
            created: boolean;
            /** Demand Id */
            demand_id: string;
            /** Status */
            status: string;
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
        /** ReviewBasisReference */
        ReviewBasisReference: {
            /** Evidence Sha256 */
            evidence_sha256: string;
            /** Review Id */
            review_id: string;
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
            /** Version */
            version: string | null;
        };
        /** SymbolBatchReprocessRequest */
        SymbolBatchReprocessRequest: {
            /** Occurrence Ids */
            occurrence_ids?: string[];
        };
        /** SymbolHealthResponse */
        SymbolHealthResponse: {
            /** Affected Occurrence Count */
            affected_occurrence_count: number;
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
            /** Artifact Entry Id */
            artifact_entry_id?: string | null;
            /** Availability */
            availability?: ("validating" | "waiting_for_pair" | "symbols_available" | "identity_conflict" | "no_debug_identity" | "storage_unavailable") | null;
            /** Blob Id */
            blob_id?: string | null;
            /** Current Version */
            current_version?: string | null;
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
            /** Version */
            version?: string | null;
            /**
             * Version Conflict
             * @default false
             */
            version_conflict: boolean;
            /** Workspace Id */
            workspace_id?: string | null;
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
        /** UploadV3Init */
        UploadV3Init: {
            /**
             * File Kind
             * @enum {string}
             */
            file_kind: "pe" | "pdb" | "dmp";
            /** Filename */
            filename: string;
            /** Sha256 */
            sha256?: string | null;
            /** Size */
            size: number;
            /**
             * Source
             * @default api
             * @enum {string}
             */
            source: "api" | "cli" | "browser";
            /** Version */
            version?: string | null;
            /** Workspace Id */
            workspace_id: string | null;
        };
        /** VersionCountResponse */
        VersionCountResponse: {
            /** Count */
            count: number;
            /** Version */
            version: string | null;
        };
        /** VersionDistributionResponse */
        VersionDistributionResponse: {
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
    list_v3_artifacts_api_v3_artifacts_get: {
        parameters: {
            query?: {
                workspace_id?: string | null;
                version?: string | null;
                filename?: string | null;
                availability?: string | null;
                limit?: number;
                cursor?: string | null;
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
                    "application/json": components["schemas"]["ArtifactPageResponse"];
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
    get_v3_artifact_api_v3_artifacts__artifact_id__get: {
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
                    "application/json": components["schemas"]["ArtifactEntryResponse"];
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
    capabilities_api_v3_capabilities_get: {
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
    get_group_api_v3_groups__group_id__get: {
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
    patch_group_api_v3_groups__group_id__patch: {
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
    unsupported_group_edit_api_v3_groups__group_id__merge_post: {
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
    unsupported_group_edit_api_v3_groups__group_id__split_post: {
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
    get_occurrence_api_v3_occurrences__occurrence_id__get: {
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
    get_analysis_api_v3_occurrences__occurrence_id__analysis_get: {
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
            /** @description Original immutable Canonical 2.0 bytes */
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
    download_dump_api_v3_occurrences__occurrence_id__download_get: {
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
    occurrence_events_api_v3_occurrences__occurrence_id__events_get: {
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
    get_modules_api_v3_occurrences__occurrence_id__modules_get: {
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
            /** @description Selected Canonical section (2.0) */
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
    reprocess_api_v3_occurrences__occurrence_id__reprocess_post: {
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
    get_threads_api_v3_occurrences__occurrence_id__threads_get: {
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
            /** @description Selected Canonical section (2.0) */
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
    patch_occurrence_time_api_v3_occurrences__occurrence_id__time_patch: {
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
    patch_occurrence_version_api_v3_occurrences__occurrence_id__version_patch: {
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
                "application/json": components["schemas"]["OccurrenceVersionPatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OccurrenceVersionResponse"];
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
    platform_overview_api_v3_platform_overview_get: {
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
    get_run_analysis_api_v3_runs__run_id__analysis_get: {
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
            /** @description Original immutable Canonical 2.0 bytes */
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
    get_pair_origins_api_v3_symbol_catalog_pairs__pair_id__origins_get: {
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
    list_pair_reviews_api_v3_symbol_catalog_pairs__pair_id__reviews_get: {
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
    submit_pair_review_api_v3_symbol_catalog_pairs__pair_id__reviews_post: {
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
    get_review_evidence_api_v3_symbol_catalog_pairs__pair_id__reviews__review_id__evidence_get: {
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
    get_v3_upload_api_v3_uploads__upload_id__get: {
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
    complete_v3_upload_api_v3_uploads__upload_id__complete_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                upload_id: string;
            };
            cookie?: never;
        };
        requestBody: {
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
    initialize_v3_upload_api_v3_uploads_init_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UploadV3Init"];
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
    list_workspaces_api_v3_workspaces_get: {
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
    create_workspace_api_v3_workspaces_post: {
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
    get_workspace_api_v3_workspaces__workspace_id__get: {
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
    list_groups_api_v3_workspaces__workspace_id__groups_get: {
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
    get_in_app_rules_api_v3_workspaces__workspace_id__in_app_rules_get: {
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
    update_in_app_rules_api_v3_workspaces__workspace_id__in_app_rules_put: {
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
    post_module_role_api_v3_workspaces__workspace_id__module_roles_post: {
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
    list_occurrences_api_v3_workspaces__workspace_id__occurrences_get: {
        parameters: {
            query?: {
                from?: string | null;
                to?: string | null;
                crash_type?: ("crash" | "hang" | "unknown" | "no_current") | null;
                latest_status?: ("UPLOADED" | "VALIDATING" | "INSPECTED" | "MATCHING_SYMBOLS" | "WAITING_FOR_SYMBOLS" | "SYMBOLS_READY" | "QUEUED" | "ANALYZING" | "NORMALIZING" | "GROUPING" | "COMPLETE" | "PARTIAL" | "FAILED" | "REJECTED" | "CANCELLED" | "TIMEOUT" | "OOM") | null;
                version?: string | null;
                test_label?: string | null;
                test_batch?: string | null;
                grouping?: ("exact" | "unclassified") | null;
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
    get_analysis_demand_api_v3_workspaces__workspace_id__occurrences__occurrence_id__analysis_demand_get: {
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
    restart_analysis_demand_api_v3_workspaces__workspace_id__occurrences__occurrence_id__analysis_demand_restarts_post: {
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
    list_analysis_history_api_v3_workspaces__workspace_id__occurrences__occurrence_id__analysis_history_get: {
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
    get_analysis_differences_api_v3_workspaces__workspace_id__occurrences__occurrence_id__analysis_history__run_id__differences_get: {
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
    list_result_reviews_api_v3_workspaces__workspace_id__occurrences__occurrence_id__result_reviews_get: {
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
    submit_result_review_api_v3_workspaces__workspace_id__occurrences__occurrence_id__result_reviews_post: {
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
    get_result_review_api_v3_workspaces__workspace_id__occurrences__occurrence_id__result_reviews__review_id__get: {
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
    get_result_review_evidence_api_v3_workspaces__workspace_id__occurrences__occurrence_id__result_reviews__review_id__evidence_get: {
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
    list_submissions_api_v3_workspaces__workspace_id__occurrences__occurrence_id__submissions_get: {
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
    workspace_overview_api_v3_workspaces__workspace_id__overview_get: {
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
    symbol_health_api_v3_workspaces__workspace_id__symbols_health_get: {
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
    missing_symbols_api_v3_workspaces__workspace_id__symbols_missing_get: {
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
    batch_reprocess_symbols_api_v3_workspaces__workspace_id__symbols_reprocess_post: {
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
