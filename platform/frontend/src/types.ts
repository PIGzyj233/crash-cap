import type { paths as GeneratedOpenApiPaths } from './generated/openapi'

/**
 * The API contract is generated from the local FastAPI app and checked in a
 * reproducible way. Domain/view models below stay intentionally hand-shaped
 * until each client call is migrated to the generated operation types.
 */
export type OpenApiPaths = GeneratedOpenApiPaths

export type UploadKind = 'pe' | 'pdb' | 'source_bundle'

/** Phase 1 currently registers x86_64 builds only. */
export type BuildArchitecture = 'x86_64'
export type CaptureProfile = 'light-crash' | 'rich-crash' | 'hang' | 'full-memory'
export type UploadLifecycleStatus =
  | 'INITIALIZED'
  | 'UPLOADING'
  | 'UPLOADED'
  | 'VERIFYING'
  | 'ACCEPTED'
  | 'QUARANTINED'
  | 'REJECTED'

export type VerificationStatus =
  | 'pending'
  | 'verified'
  | 'rejected_fastlink'
  | 'pdb_mismatch'
  | 'pe_mismatch'
  | 'corrupted'
  | 'rejected_format'

export type AnalysisStatus =
  | 'UPLOADED'
  | 'VALIDATING'
  | 'INSPECTED'
  | 'MATCHING_SYMBOLS'
  | 'WAITING_FOR_SYMBOLS'
  | 'SYMBOLS_READY'
  | 'QUEUED'
  | 'ANALYZING'
  | 'NORMALIZING'
  | 'GROUPING'
  | 'COMPLETE'
  | 'PARTIAL'
  | 'FAILED'
  | 'REJECTED'
  | 'CANCELLED'
  | 'TIMEOUT'
  | 'OOM'

export type ResolutionMethod = 'reported' | 'auto_unique' | 'manual' | 'ambiguous' | 'unresolved'
export type CrashType = 'crash' | 'hang' | 'unknown'
export type GroupStatus = 'open' | 'investigating' | 'fixed' | 'ignored'
export type GroupType = 'exact'
export type FrameTrust = 'context' | 'cfi' | 'frame_pointer' | 'scan' | 'unknown'
export type QualityWarningCode =
  | 'missing_pe'
  | 'missing_pdb'
  | 'pdb_mismatch'
  | 'pe_mismatch'
  | 'missing_pe_unwind'
  | 'system_symbol_pending'
  | 'system_symbol_failed'
  | 'truncated_dump'
  | 'scan_frames'
  | 'module_limit_truncated'
  | 'unsupported_inline'
  | 'ambiguous_build'
  | 'unresolved_build'
  | 'unknown_crash_type'
  | 'unclassified_exact'
  | 'other'

export interface Workspace {
  id: string
  name: string
  display_name: string
  platform: 'windows' | string
  default_architecture: BuildArchitecture
  retention_days: number
  symbol_inventory_version: number
  in_app_rule_version: number
  in_app_rules: { include_modules: string[]; exclude_modules: string[] }
  created_at: string
}

export interface TopGroup {
  id: string
  title: string
  fingerprint: string
  occurrence_count: number
  status: GroupStatus
  first_seen: string
  last_seen: string
}

export interface VersionCount {
  version: string | null
  count: number
}

export interface WorkspaceOverview {
  window_start: string
  window_end: string
  crash_occurrences: number
  exact_groups: number
  unclassified: number
  versions: VersionCount[]
  top_groups: TopGroup[]
  symbol_completeness: number
  failure_rate: number
  average_analysis_duration_ms: number
  hang_captures: number
  unknown_captures: number
  rejected_uploads: number
}

export interface BuildModule {
  id: string
  code_file: string
  debug_file: string | null
  role: 'entrypoint' | 'owned' | 'dependency'
  code_id: string | null
  debug_id: string | null
  in_app: boolean
  artifact_count?: number
  missing_occurrence_count?: number
}

export interface Artifact {
  id: string
  module_id: string | null
  kind: UploadKind
  logical_name: string
  sha256: string
  size: number
  code_id: string | null
  debug_id: string | null
  verification_status: VerificationStatus
  ingest_metadata: {
    policy_version?: string
    source_entry_count?: number
    entry_count?: number
    uncompressed_size?: number
  } | null
  created_at: string
}

export interface Build {
  id: string
  workspace_id: string
  version: string
  build_number: string | null
  commit_sha: string | null
  channel: string | null
  architecture: BuildArchitecture
  toolchain: string | null
  producer: 'msvc' | 'clang-cl' | 'crashpad' | null
  producer_build_id: string | null
  manifest_object_key: string | null
  manifest_schema_version: '1.0' | '2.0' | null
  source_bundle_config: SourceBundleDescriptor | null
  created_at: string
  modules: BuildModule[]
  artifacts: Artifact[]
  groups: TopGroup[]
}

export interface BuildCreateInput {
  version: string
  build_number?: string
  commit_sha?: string
  channel?: string
  architecture?: BuildArchitecture
  toolchain?: string
  producer?: 'msvc' | 'clang-cl' | 'crashpad'
  producer_build_id?: string
}

export interface ManifestModuleInput {
  code_file: string
  debug_file: string
  role: 'entrypoint' | 'owned' | 'dependency'
  code_id?: string
  debug_id?: string
}

export interface BuildManifestInput {
  schema_version: '1.0' | '2.0'
  product: string
  version: string
  channel?: string
  commit?: string
  build_number?: string
  architecture: BuildArchitecture
  compiler?: string
  toolchain?: string
  modules: ManifestModuleInput[]
  source_bundle?: SourceBundleDescriptor
}

export interface SourceBundleDescriptor {
  schema_version: '1.0'
  archive: string
  source_root: string
  strip_prefixes?: string[]
  context_lines?: number
}

export interface BlobSummary {
  id: string
  sha256: string
  size: number
  dump_kind: 'user_minidump' | 'kernel' | 'unknown_binary'
  verification_status: VerificationStatus | 'verifying' | 'accepted' | 'rejected' | 'quarantined'
  uploaded_at: string
  expires_at: string | null
  deleted_at: string | null
}

export interface QualityWarning {
  code: QualityWarningCode
  message: string
  module?: string | null
  debug_id?: string | null
}

export interface StackFrame {
  index: number
  instruction_addr: string
  module: string | null
  module_debug_id: string | null
  relative_addr: string | null
  function: string | null
  function_raw: string | null
  function_normalized: string | null
  function_offset: number | null
  file: string | null
  line: number | null
  trust: FrameTrust
  inline: boolean
  in_app: boolean
  source_context: {
    pre: string[]
    line: string
    post: string[]
  } | null
}

export interface Thread {
  id: number
  name: string | null
  is_crashing: boolean
  frames: StackFrame[]
}

export interface AnalysisModule {
  code_file: string | null
  code_id: string | null
  debug_file: string | null
  debug_id: string | null
  image_base: string | null
  image_size: number | null
  role: 'entrypoint' | 'owned' | 'dependency' | 'system' | 'unknown'
  in_app: boolean
  artifact_ids: string[]
  status: 'matched' | 'missing_pe' | 'missing_pdb' | 'pdb_mismatch' | 'pe_mismatch' | 'corrupted' | 'system_symbol_pending' | 'unsupported'
}

export interface CanonicalReport {
  schema_version: '1.0'
  workspace_id: string
  occurrence_id: string
  analysis_id: string
  engine: {
    core_version: string
    core_image_digest: string
    symbolicator_version: string
    grouping_version: string
    normalization_version: string
  }
  build_resolution: {
    reported_build_id: string | null
    resolved_build_id: string | null
    resolution_method: ResolutionMethod
    evidence: {
      candidate_build_ids: string[]
      matched_entrypoints: string[]
      matched_owned_modules: string[]
      conflicting_modules: string[]
      note?: string | null
    }
  }
  dump: {
    blob_id: string
    sha256: string
    kind: 'user_minidump' | 'kernel' | 'unknown_binary'
    size: number
    capture_profile: 'light-crash' | 'rich-crash' | 'hang' | 'full-memory' | null
    dump_timestamp: string | null
    reported_at: string | null
    uploaded_at: string
    occurred_at: string
    time_source: 'dump' | 'reported' | 'uploaded' | 'manual'
  }
  process: {
    pid: number | null
    architecture: 'x86_64' | 'x86' | 'arm64' | 'unknown'
    os: string
    os_version: string | null
    uptime_seconds: number | null
  }
  crash: {
    type: CrashType
    type_evidence: 'exception_stream' | 'reported_hang' | 'insufficient' | 'other'
    thread_id: number | null
    exception_code: string | null
    exception_name: string | null
    access_type: 'read' | 'write' | 'execute' | 'readwrite' | null
    address: string | null
    fault_module: string | null
    fault_module_debug_id: string | null
  }
  threads: Thread[]
  modules: AnalysisModule[]
  quality: {
    score: number
    symbol_coverage: number
    unwind_reliability: number
    artifact_completeness: number
    warnings: QualityWarning[]
  }
  fingerprints: {
    exact: string | null
    family: null
    algorithm: string
  }
}

/** Backwards-compatible name for callers that still use the old UI term. */
export type CanonicalAnalysis = CanonicalReport

export interface AnalysisRunSummary {
  id: string
  status: AnalysisStatus
  resolution_method: ResolutionMethod
  resolved_build_id: string | null
  quality_score: number | null
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  result?: CanonicalReport | null
  error_code?: string | null
}

export interface ReprocessResponse extends AnalysisRunSummary {
  created: boolean
}

export interface CrashGroup {
  id: string
  workspace_id: string
  group_type: GroupType
  fingerprint: string
  title: string
  status: GroupStatus
  owner: string | null
  issue_url: string | null
  first_seen: string
  last_seen: string
  occurrence_count: number
  first_build_id: string | null
  last_build_id: string | null
  representative_stack: StackFrame[]
  build_distribution: Array<{ build_id: string; version: string; count: number }>
  occurrence_ids: string[]
}

/** Shape returned by workspace/build group list endpoints. */
export interface CrashGroupSummary {
  id: string
  workspace_id: string
  group_type: GroupType
  fingerprint: string
  title: string
  status: GroupStatus
  owner: string | null
  issue_url: string | null
  first_seen: string
  last_seen: string
  occurrence_count: number
  first_build_id: string | null
  last_build_id: string | null
}

export interface OccurrenceDetail {
  id: string
  workspace_id: string
  blob: BlobSummary
  reported_build_id: string | null
  occurred_at: string
  uploaded_at: string
  time_source: 'dump' | 'reported' | 'uploaded' | 'manual'
  current_analysis: AnalysisRunSummary | null
  latest_attempt: AnalysisRunSummary | null
  group: TopGroup | null
}

export interface SymbolHealthRow {
  build_id: string | null
  module_id: string | null
  code_file: string
  debug_file: string | null
  code_id: string | null
  debug_id: string | null
  status: 'matched' | 'missing' | 'mismatch'
  affected_occurrence_count: number
  first_seen: string
  last_seen: string
  occurrence_ids: string[]
}

export interface BatchReprocessResponse {
  workspace_id: string
  affected_occurrence_count: number
  created_run_count: number
  occurrence_ids: string[]
  run_ids: string[]
}

export interface OccurrenceProgressEvent {
  occurrence_id: string
  run: AnalysisRunSummary
  current_run_id: string | null
}

export interface InitUploadResponse {
  upload_id: string
  method: 'PUT' | 'POST'
  url: string
  headers: Record<string, string>
  expires_in: number
  multipart?: {
    upload_id: string
    parts: Array<{ part_number: number; url: string }>
  }
}

export interface UploadCompletePart {
  part_number: number
  etag: string
}

export interface CompleteUploadRequest {
  etag?: string | null
  multipart_upload_id?: string | null
  parts: UploadCompletePart[]
}

export interface CompleteUploadResponse {
  upload_id: string
  status: UploadLifecycleStatus
  verification_status: UploadLifecycleStatus
  sha256?: string
  occurrence_id?: string | null
  blob_id?: string | null
  duplicate?: boolean
}

export interface ApiErrorBody {
  error?: { code?: string; message?: string; request_id?: string }
}

export interface RawDownloadState {
  enabled: boolean
  reason?: string
}

export interface PresignedDownload {
  url: string
  expires_at: string
}

export interface ApiClientOptions {
  baseUrl?: string
  fetcher?: typeof fetch
  rawDownloadEnabled?: boolean
}
