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

export type Workspace = Schemas['WorkspaceResponse']
export type WorkspaceOverview = Schemas['OverviewResponse']
export type PlatformOverview = Schemas['PlatformOverviewResponse']
export type PlatformWorkspaceSummary = Schemas['PlatformWorkspaceSummaryResponse']
export type TopGroup = Schemas['GroupSummaryResponse']
export type VersionCount = Schemas['VersionCountResponse']

export type Build = Schemas['BuildResponse']
export type BuildModule = Schemas['BuildModuleResponse']
export type Artifact = Schemas['ArtifactResponse']
export type BuildPublicationStatus = Schemas['BuildPublicationStatusResponse']
export type BuildPublication = Schemas['BuildPublicationSummaryResponse']
export type ArtifactExpectation = Schemas['ArtifactExpectationResponse']
export type ArtifactProducer = Schemas['ArtifactProducerResponse']
export type BuildArchitecture = Build['architecture']
export type UploadKind = Artifact['kind']
export type VerificationStatus = Artifact['verification_status']

export type BlobSummary = Schemas['BlobResponse']
export type AnalysisRunSummary = Schemas['AnalysisRunResponse']
export type AnalysisStatus = AnalysisRunSummary['status']
export type ResolutionMethod = AnalysisRunSummary['resolution_method']

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

export type CanonicalReport = Schemas['CanonicalAnalysisResult']
export type CanonicalAnalysis = CanonicalReport
export type StackFrame = Schemas['CanonicalFrame']
export type Thread = Schemas['CanonicalThread']
export type AnalysisModule = Schemas['CanonicalModule']
export type QualityWarning = Schemas['CanonicalQualityWarning']
export type FrameTrust = Schemas['CanonicalTrust']
export type QualityWarningCode = QualityWarning['code']
export type CrashType = CanonicalReport['crash']['type']

export type InitUploadResponse = Schemas['UploadInitResponse']
export type CompleteUploadResponse = Schemas['UploadCompletionResponse']
export type UploadLifecycleStatus = CompleteUploadResponse['status']
export type UploadCompletePart = Schemas['MultipartPart']
export type CompleteUploadRequest = Schemas['UploadComplete']
export type PresignedDownload = Schemas['PresignedDownloadResponse']
export type CaptureProfile = NonNullable<Schemas['DumpUploadInit']['capture_profile']>
export type BuildCreateInput = Schemas['BuildCreate']

/**
 * The Build Manifest request is governed by build-manifest-v1/v2.schema.json;
 * the API deliberately accepts and validates that document without copying it
 * into a Pydantic request model.
 */
export interface ManifestModuleInput {
  code_file: string
  debug_file: string
  role: 'entrypoint' | 'owned' | 'dependency'
  code_id?: string
  debug_id?: string
}

export interface SourceBundleDescriptor {
  schema_version: '1.0'
  archive: string
  source_root: string
  strip_prefixes?: string[]
  context_lines?: number
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
  fetcher?: typeof fetch
  rawDownloadEnabled?: boolean
}

export interface OccurrenceListParams {
  from?: string
  to?: string
  crash_type?: 'crash' | 'hang' | 'unknown' | 'no_current'
  latest_status?: AnalysisStatus
  resolution_method?: ResolutionMethod | 'no_current'
  version?: string
  build_id?: string
  grouping?: 'exact' | 'unclassified' | 'no_current'
  q?: string
  cursor?: string
  limit?: number
}
