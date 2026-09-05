import type {
components as GeneratedOpenApiComponents,
paths as GeneratedOpenApiPaths,
} from './generated/openapi'

/**
 * Server representations come from the checked-in OpenAPI document. Request
 * shapes that intentionally use an external JSON Schema (Build Manifest) stay
 * local and are called out below.
 */
export type OpenApiPaths = GeneratedOpenApiPaths
type Schemas = GeneratedOpenApiComponents['schemas']
export type SubmissionPage = Schemas['SubmissionPage']

export type Workspace = Schemas['WorkspaceResponse']
export type WorkspaceOverview = Schemas['OverviewResponse']
export type PlatformOverview = Schemas['PlatformOverviewResponse']
export type PlatformWorkspaceSummary = Schemas['PlatformWorkspaceSummaryResponse']
export type TopGroup = Schemas['GroupSummaryResponse']
export type VersionCount = Schemas['VersionCountResponse']

export type BlobSummary = Schemas['BlobResponse']
export type AnalysisRunSummary = Schemas['AnalysisRunResponse']
export type AnalysisStatus = AnalysisRunSummary['status']

export type CrashGroup = Schemas['GroupDetailResponse']
export type CrashGroupSummary = Schemas['GroupSummaryResponse']
export type GroupStatus = CrashGroupSummary['status']
export type GroupType = CrashGroupSummary['group_type']
export type OccurrenceDetail = Schemas['OccurrenceResponse']
export type OccurrenceListItem = Schemas['OccurrenceListItemResponse']
export type OccurrenceListPage = Schemas['OccurrenceListPageResponse']
export type OccurrenceListSummary = Schemas['OccurrenceListSummaryResponse']
export type SymbolHealthRow = Schemas['SymbolHealthResponse']
export type BatchReprocessResponse = Schemas['BatchReprocessResponse']
export type ReprocessResponse = Schemas['ReprocessResponse']
export type Capabilities = Schemas['CapabilitiesResponse']
export type ModuleRoleRequest = Schemas['ModuleRoleRequest']
export type ModuleRoleResponse = Schemas['ModuleRoleResponse']

export type CanonicalReport = Schemas['CanonicalAnalysisResult']
export type CanonicalAnalysis = CanonicalReport
export type StackFrame = Schemas['CanonicalFrame']
export type Thread = Schemas['CanonicalThread']
export type AnalysisModule = Schemas['CanonicalModule']
export type QualityWarning = Schemas['CanonicalQualityWarning']
export type UnwindMethod = Schemas['CanonicalFrame']['unwind_method']
export type FrameTrust = Schemas['CanonicalTrust']
export type QualityWarningCode = QualityWarning['code']
export type CrashType = CanonicalReport['crash']['type']

export type InitUploadResponse = Schemas['UploadInitResponse']
export type CompleteUploadResponse = Schemas['UploadCompletionResponse']
export type UploadLifecycleStatus = CompleteUploadResponse['status']
export type UploadCompletePart = Schemas['MultipartPart']
export type CompleteUploadRequest = Schemas['UploadComplete']
export type PresignedDownload = Schemas['PresignedDownloadResponse']

/** SSE data is framed separately from ordinary JSON HTTP responses. */
export interface OccurrenceProgressEvent {
  occurrence_id: string
  run: AnalysisRunSummary
  current_run_id: string | null
}

/** Error parsing remains defensive because an upstream gateway may answer. */
export interface ApiErrorBody {
  error?: { code?: string; message?: string; request_id?: string }
}

export interface RawDownloadState {
  enabled: boolean
  reason?: string
}

export interface ApiClientOptions {
  baseUrl?: string
  analysisBaseUrl?: string
  fetcher?: typeof fetch
  rawDownloadEnabled?: boolean
}

export interface OccurrenceListParams {
  test_label?: string
  test_batch?: string
  from?: string
  to?: string
  crash_type?: 'crash' | 'hang' | 'unknown' | 'no_current'
  latest_status?: AnalysisStatus
  version?: string
  grouping?: 'exact' | 'unclassified' | 'no_current'
  q?: string
  cursor?: string
  limit?: number
}

export type ArtifactEntry = Schemas['ArtifactEntryResponse']
export type ArtifactPage = Schemas['ArtifactPageResponse']
export type UploadInput = Schemas['UploadV3Init']
