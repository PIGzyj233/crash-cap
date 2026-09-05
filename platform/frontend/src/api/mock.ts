import type { AnalysisModule,CanonicalReport,CompleteUploadRequest,CrashGroup,CrashGroupSummary,InitUploadResponse,OccurrenceDetail,OccurrenceListItem,PlatformOverview,StackFrame,SymbolHealthRow,Workspace,WorkspaceOverview } from '../types'
import { createApiClient } from './client'

const now = new Date('2026-08-21T08:00:00.000Z')
const iso = (minutes: number) => new Date(now.getTime() - minutes * 60_000).toISOString()

const workspace: Workspace = {
  id: 'wsp_demo',
  name: 'desktop-client',
  display_name: 'Desktop Client',
  platform: 'windows',
  default_architecture: 'x86_64',
  retention_days: 180,
  symbol_inventory_version: 12,
  in_app_rule_version: 1,
  in_app_rules: { include_modules: ['render.dll'], exclude_modules: [] },
  created_at: iso(60 * 24 * 20),
}

const frame = (index: number, functionName: string, module: string, trust: 'context' | 'cfi' | 'frame_pointer' | 'scan', inApp = true): StackFrame => ({
  module_index: 0, physical_frame_index: index, unwind_method: trust === 'cfi' ? 'call_frame_info' : trust,
  index,
  instruction_addr: `0x140001${(index * 0x120).toString(16).padStart(3, '0')}`,
  module,
  module_debug_id: inApp ? 'b0c27c20a4704c4fa6f2b706d29f7e031' : null,
  relative_addr: `0x${(0x1000 + index * 0x120).toString(16)}`,
  function: functionName,
  function_raw: functionName,
  function_normalized: functionName,
  function_offset: index * 0x20,
  file: inApp ? `src/${module.replace(/\.exe$|\.dll$/i, '').toLowerCase()}.cpp` : null,
  line: inApp ? 120 + index * 16 : null,
  trust,
  in_app: inApp,
  inline: index === 1,
  source_context: null,
})

function module(index: number, value: Omit<AnalysisModule, 'module_index' | 'selection' | 'source_outcomes'>): AnalysisModule {
  return { ...value, module_index:index, source_outcomes:[], selection:{module_index:index,identity:{code_id:value.code_id ?? null,debug_id:value.debug_id ?? null,architecture:'x86_64'},state:'none',reason:'missing',candidate_pair_ids:[],unavailable_pair_ids:[],selected_pair_id:null,candidates_complete:true,candidate_evidence:{object_key:'candidates.json',sha256:'a'.repeat(64)},review_refs:[]} }
}

const canonical: CanonicalReport = {
  schema_version: '2.0',
  workspace_id: workspace.id,
  occurrence_id: 'occ_demo',
  analysis_id: 'run_demo',
  engine: {
    core_version: 'dmp-core 1.0.0',
    core_image_digest: 'sha256:' + 'a'.repeat(64),
    symbolicator_version: 'symbolicator 24.7',
    grouping_version: 'group-v1.1',
    normalization_version: 'norm-v1.0',
  },
  symbol_resolution: { selection_version: 'pair-selection-v1', resolution_evidence_fingerprint:'e'.repeat(64), inspect_sha256:'i'.repeat(64), context_sha256:'c'.repeat(64), selection:{object_key:'selection.json',sha256:'a'.repeat(64)} },
  dump: {
    blob_id: 'blob_demo',
    sha256: 'd'.repeat(64),
    kind: 'user_minidump',
    size: 12_582_912,
    capture_profile: 'rich-crash',
    dump_timestamp: iso(20),
    reported_at: null,
    uploaded_at: iso(18),
    occurred_at: iso(20),
    time_source: 'dump',
  },
  process: { pid: 4420, architecture: 'x86_64', os: 'Windows', os_version: '11 23H2', uptime_seconds: 18420 },
  crash: {
    type: 'crash',
    type_evidence: 'exception_stream',
    thread_id: 7,
    exception_code: '0xc0000005',
    exception_name: 'EXCEPTION_ACCESS_VIOLATION',
    access_type: 'read',
    address: '0x0000000000000000',
    fault_module: 'render.dll',
    fault_module_debug_id: 'b0c27c20a4704c4fa6f2b706d29f7e031',
  },
  threads: [
    { id: 7, name: 'RenderWorker', is_crashing: true, frames: [frame(0, 'Renderer::SubmitFrame', 'render.dll', 'context'), frame(1, 'Renderer::FlushQueue', 'render.dll', 'cfi'), frame(2, 'App::Tick', 'desktop-client.exe', 'frame_pointer'), frame(3, 'BaseThreadInitThunk', 'kernel32.dll', 'scan', false)] },
    { id: 3, name: 'MainThread', is_crashing: false, frames: [frame(0, 'App::Run', 'desktop-client.exe', 'cfi'), frame(1, 'BaseThreadInitThunk', 'kernel32.dll', 'scan', false)] },
  ],
  modules: [
    module(0, { code_file: 'desktop-client.exe', debug_file: 'desktop-client.pdb', code_id: '67A1B9231F000', debug_id: 'b0c27c20a4704c4fa6f2b706d29f7e031', image_base: '0x140000000', image_size: 12_582_912, role: 'owned', in_app: true, artifact_ids: ['art_app_pe', 'art_app_pdb'], status: 'matched' }),
    module(1, { code_file: 'render.dll', debug_file: 'render.pdb', code_id: '67A1B925A1000', debug_id: '94e72158e9a3443c787b78a8a3448d0d730', image_base: '0x180000000', image_size: 4_194_304, role: 'owned', in_app: true, artifact_ids: ['art_render_pe', 'art_render_pdb'], status: 'matched' }),
    module(2, { code_file: 'ucrtbase.dll', debug_file: null, code_id: null, debug_id: null, image_base: null, image_size: null, role: 'system', in_app: false, artifact_ids: [], status: 'system_symbol_pending' }),
  ],
  quality: {
    score: 0.91,
    symbol_coverage: 0.93,
    unwind_reliability: 0.9,
    artifact_completeness: 0.88,
    warnings: [
      { code: 'scan_frames', message: '线程 7 的第 4 帧由 scan unwind 得到，标记为低可信。', module: 'kernel32.dll', debug_id: null },
    ],
  },
  fingerprints: { exact: 'e'.repeat(64), family: null, algorithm: 'exact-v1.1' },
}

const primaryGroup: CrashGroupSummary = {
  id: 'grp_demo',
  workspace_id: workspace.id,
  group_type: 'exact',
  title: 'EXCEPTION_ACCESS_VIOLATION · Renderer::SubmitFrame',
  fingerprint: 'e'.repeat(64),
  occurrence_count: 23,
  status: 'open',
  owner: null,
  issue_url: null,
  first_seen: iso(60 * 24 * 7),
  last_seen: iso(20),
}

const overview: WorkspaceOverview = {
  window_start: iso(60 * 24 * 7),
  window_end: now.toISOString(),
  crash_occurrences: 128,
  exact_groups: 14,
  unclassified: 19,
  versions: [{ version: '2026.08.21.1', count: 45 }, { version: '2026.08.20.3', count: 38 }, { version: '2026.08.19.8', count: 26 }, { version: null, count: 19 }],
  top_groups: [primaryGroup, { ...primaryGroup, id: 'grp_2', title: 'EXCEPTION_ILLEGAL_INSTRUCTION · Cpu::Dispatch', fingerprint: 'f'.repeat(64), occurrence_count: 14, status: 'investigating', first_seen: iso(60 * 24 * 5), last_seen: iso(60 * 50) }],
  symbol_completeness: 0.87,
  failure_rate: 0.032,
  average_analysis_duration_ms: 42_800,
  hang_captures: 4,
  unknown_captures: 8,
  rejected_uploads: 3,
}

const occurrence: OccurrenceDetail = {
  id: 'occ_demo',
  workspace_id: workspace.id,
  blob: { id: 'blob_demo', sha256: 'd'.repeat(64), size: 12_582_912, dump_kind: 'user_minidump', verification_status: 'accepted', uploaded_at: iso(18), expires_at: new Date(now.getTime() + 180 * 86_400_000).toISOString(), deleted_at: null },
  version: '2026.08.21.1',
  dump_timestamp: iso(20),
  reported_at: null,
  occurred_at: iso(20),
  uploaded_at: iso(18),
  time_source: 'dump',
  current_analysis: { id: 'run_demo', status: 'COMPLETE', quality_score: canonical.quality.score, started_at: iso(17), finished_at: iso(16), duration_ms: 42_800, error_code: null, error_detail: null },
  latest_attempt: { id: 'run_demo', status: 'COMPLETE', quality_score: canonical.quality.score, started_at: iso(17), finished_at: iso(16), duration_ms: 42_800, error_code: null, error_detail: null },
  group: primaryGroup,
}

const groups: CrashGroup[] = [{
  id: 'grp_demo', workspace_id: workspace.id, group_type: 'exact', fingerprint: 'e'.repeat(64), title: 'EXCEPTION_ACCESS_VIOLATION · Renderer::SubmitFrame', status: 'open', owner: null, issue_url: null, first_seen: iso(60 * 24 * 7), last_seen: iso(20), occurrence_count: 23, representative_stack: canonical.threads[0].frames.slice(0, 3), version_distribution: [{ version: '2026.08.21.1', count: 18 }, { version: '2026.08.19.8', count: 5 }], occurrence_ids: ['occ_demo'],
}]

const symbols: SymbolHealthRow[] = [
  { code_file: 'desktop-client.exe', debug_file: 'desktop-client.pdb', code_id: '67A1B9231F000', debug_id: canonical.crash.fault_module_debug_id ?? null, status: 'matched', affected_occurrence_count: 0, first_seen: iso(60 * 24 * 30), last_seen: iso(20), occurrence_ids: [] },
  { code_file: 'render.dll', debug_file: 'render.pdb', code_id: '67A1B925A1000', debug_id: '94e72158e9a3443c787b78a8a3448d0d730', status: 'matched', affected_occurrence_count: 0, first_seen: iso(60 * 24 * 30), last_seen: iso(20), occurrence_ids: [] },
  { code_file: 'ucrtbase.dll', debug_file: null, code_id: null, debug_id: null, status: 'missing', affected_occurrence_count: 17, first_seen: iso(60 * 24 * 10), last_seen: iso(60), occurrence_ids: ['occ_demo'] },
  { code_file: 'render.dll', debug_file: 'render.pdb', code_id: 'old', debug_id: 'old-debug-id', status: 'mismatch', affected_occurrence_count: 2, first_seen: iso(60 * 24 * 2), last_seen: iso(60 * 3), occurrence_ids: ['occ_demo'] },
]

const occurrenceListItem: OccurrenceListItem = {
  version: '2026.08.21.1',
  id: occurrence.id,
  workspace_id: workspace.id,
  occurred_at: occurrence.occurred_at,
  uploaded_at: occurrence.uploaded_at,
  time_source: occurrence.time_source,
  current_analysis: occurrence.current_analysis,
  latest_attempt: occurrence.latest_attempt,
  summary: {
    crash_type: 'crash',
    exception_code: canonical.crash.exception_code ?? null,
    exception_name: canonical.crash.exception_name ?? null,
    access_type: canonical.crash.access_type ?? null,
    fault_module: canonical.crash.fault_module ?? null,
    top_function: canonical.threads[0].frames[0].function ?? null,
    version: '2026.08.21.1',
  },
  group: occurrence.group,
}

const processingOccurrence: OccurrenceListItem = {
  ...occurrenceListItem,
  id: 'occ_processing',
  current_analysis: null,
  latest_attempt: { ...occurrenceListItem.latest_attempt!, id: 'run_processing', status: 'ANALYZING', finished_at: null, duration_ms: null },
  summary: null,
  group: null,
}

const latestFailedOccurrence: OccurrenceListItem = {
  ...occurrenceListItem,
  id: 'occ_latest_failed',
  latest_attempt: { ...occurrenceListItem.latest_attempt!, id: 'run_latest_failed', status: 'FAILED', error_code: 'CORE_FAILED', error_detail: 'Mock retry failed' },
}

const platformOverview: PlatformOverview = {
  window_start: iso(60 * 24 * 7),
  window_end: now.toISOString(),
  workspace_count: 1,
  attention: { in_progress: 1, latest_attempt_failed: 1, unclassified_crashes: 0, symbol_affected_occurrences: 0 },
  workspaces: [{ workspace, occurrence_count: 3, attention_count: 2, last_occurrence_at: occurrence.occurred_at }],
  recent_occurrences: [latestFailedOccurrence, processingOccurrence, occurrenceListItem],
}

export type MockScenario = 'default' | 'empty-platform' | 'empty-occurrences' | 'processing' | 'latest-failed' | 'role-declaration' | 'demand-coalescing'

const MOCK_SCENARIOS = new Set<MockScenario>(['default', 'empty-platform', 'empty-occurrences', 'processing', 'latest-failed', 'role-declaration', 'demand-coalescing'])

/** Browser-only visual QA switch. Production ignores it because mock mode is disabled. */
export function parseMockScenario(value: string | null): MockScenario | undefined {
  return value && MOCK_SCENARIOS.has(value as MockScenario) ? value as MockScenario : undefined
}

function jsonResponse(data: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' }, ...init })
}

export function createMockApiClient(options: { scenario?: MockScenario } = {}) {
  const scenario = options.scenario ?? 'default'
  const roleDeclarationModule = module(3, {
    code_file: 'plugin.dll',
    debug_file: 'plugin.pdb',
    code_id: '67A1B925A1000',
    debug_id: '94e72158e9a3443c787b78a8a3448d0d730',
    image_base: '0x190000000',
    image_size: 4096,
    role: 'unknown' as const,
    in_app: false,
    artifact_ids: [],
    status: 'matched' as const,
  })
  const scenarioCanonical = scenario === 'role-declaration'
    ? { ...canonical, modules: [...canonical.modules, roleDeclarationModule] }
    : canonical
  let pollCount = 0
  const uploadPollCounts = new Map<string, number>()
  const mockFetch: typeof fetch = async (input, init) => {
    const rawUrl = typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString()
    if (rawUrl.startsWith('http://rustfs.local/')) return new Response(null, { status: 200 })
    const url = new URL(rawUrl, 'http://crash-cap.local')
    const path = url.pathname.replace(/^\/api\/v3(?=\/|$)/, '')
    const method = init?.method ?? 'GET'
    if (method === 'GET' && path === '/artifacts') return jsonResponse({items:[],next_cursor:null})
    if (method === 'GET' && path === '/workspaces') return jsonResponse(scenario === 'empty-platform' ? [] : [workspace])
    if (method === 'GET' && path === `/workspaces/${workspace.id}`) return jsonResponse(workspace)
    if (method === 'GET' && path === '/platform/overview') return jsonResponse(scenario === 'empty-platform' ? { ...platformOverview, workspace_count: 0, workspaces: [], recent_occurrences: [], attention: { in_progress: 0, latest_attempt_failed: 0, unclassified_crashes: 0, symbol_affected_occurrences: 0 } } : platformOverview)
    if (method === 'GET' && path === `/workspaces/${workspace.id}/occurrences`) {
      const items = scenario === 'empty-occurrences' ? [] : scenario === 'processing' ? [processingOccurrence] : scenario === 'latest-failed' ? [latestFailedOccurrence] : [latestFailedOccurrence, processingOccurrence, occurrenceListItem]
      return jsonResponse({ items, next_cursor: null })
    }
    if (method === 'GET' && path === `/workspaces/${workspace.id}/overview`) return jsonResponse(overview)
    if (method === 'GET' && path === '/artifact-producers') return jsonResponse([{ producer: 'msvc', status: 'supported', artifact_format: 'windows-x64-msvc-full-pdb-7.0', fixture_suite: 'phase0-golden', gate: 'phase0', publication_contracts: ['1.0'], minimum_client_version: '1.0.0', build_publications_enabled: true }])
    if (method === 'GET' && path === `/workspaces/${workspace.id}/symbols/health`) return jsonResponse(symbols)
    if (method === 'GET' && path === `/workspaces/${workspace.id}/symbols/missing`) return jsonResponse(symbols.filter((item) => item.status !== 'matched'))
    if (method === 'GET' && path === `/workspaces/${workspace.id}/groups`) return jsonResponse(groups)
    if (method === 'GET' && path === `/groups/${groups[0].id}`) return jsonResponse(groups[0])
    if (method === 'GET' && path === `/occurrences/${occurrence.id}`) {
      pollCount += 1
      if (pollCount === 1) {
        occurrence.latest_attempt = { ...occurrence.latest_attempt!, status: 'ANALYZING' }
        occurrence.current_analysis = null
      } else {
        occurrence.current_analysis = { ...occurrence.latest_attempt!, status: 'COMPLETE', finished_at: iso(16), duration_ms: 42_800 }
        occurrence.latest_attempt = occurrence.current_analysis
      }
      return jsonResponse(occurrence)
    }
    if (method === 'GET' && path === `/occurrences/${occurrence.id}/analysis`) return jsonResponse(scenarioCanonical)
    if (method === 'GET' && path === `/workspaces/${workspace.id}/occurrences/${occurrence.id}/analysis-demand`) return jsonResponse(scenario === 'demand-coalescing' ? {
      demand_id: 'demand_mock', occurrence_id: occurrence.id, state: 'coalescing', generation: 2, retry_attempt: 0,
      run_id: null, reason: null, not_before: '2026-09-04T04:00:00Z',
    } : null)
    if (method === 'GET' && path === `/occurrences/${occurrence.id}/threads`) return jsonResponse(scenarioCanonical.threads)
    if (method === 'GET' && path === `/occurrences/${occurrence.id}/modules`) return jsonResponse(scenarioCanonical.modules)
    if (method === 'GET' && path === '/capabilities') return jsonResponse(scenario === 'role-declaration'
      ? { reader_versions: ['2.0'], enabled_writes: ['workspace_module_roles'], pause_reason: null }
      : { reader_versions: ['2.0'], enabled_writes: [], pause_reason: 'qualification_pending' })
    if (method === 'POST' && path === `/workspaces/${workspace.id}/module-roles`) return jsonResponse({ workspace_id: workspace.id, version: 1, ...JSON.parse(String(init?.body)), changed: true, fanout_attempt_id: 'wra_mock' }, { status: 201 })
    if (method === 'POST' && path === `/occurrences/${occurrence.id}/reprocess`) return jsonResponse({ demand_id:'demand_reprocess', status:'preparing', created:true })
    if (method === 'POST' && path === '/workspaces') return jsonResponse(workspace, { status: 201 })
    if (method === 'POST' && path === '/uploads:init') return jsonResponse({ upload_id: 'upl_dump', method: 'PUT', url: 'http://rustfs.local/dump', headers: {}, expires_in: 900 })
    if (method === 'GET' && /^\/uploads\/[^/]+$/.test(path)) {
      const uploadId = path.split('/')[2]
      const count = (uploadPollCounts.get(uploadId) ?? 0) + 1
      uploadPollCounts.set(uploadId, count)
      const accepted = count > 1
      return jsonResponse({
        upload_id: uploadId,
        status: accepted ? 'ACCEPTED' : 'VERIFYING',
        verification_status: accepted ? 'ACCEPTED' : 'VERIFYING',
        ...(accepted && uploadId === 'upl_dump' ? { occurrence_id: occurrence.id, blob_id: occurrence.blob.id, duplicate: false } : {}),
      })
    }
    if (method === 'POST' && /^\/uploads\/[^/]+:complete$/.test(path)) {
      return jsonResponse({ upload_id: path.split('/')[2], status: 'VERIFYING', verification_status: 'VERIFYING' })
    }
    return jsonResponse({ error: { code: 'NOT_FOUND', message: 'Mock route not found' } }, { status: 404 })
  }
  const api = createApiClient({ baseUrl: '/api/v3', fetcher: mockFetch, rawDownloadEnabled: false })
  return {
    ...api,
    uploadPresigned: async (upload: InitUploadResponse, _file: File, onProgress?: (percent: number) => void): Promise<CompleteUploadRequest> => {
      onProgress?.(100)
      return upload.multipart
        ? { multipart_upload_id: upload.multipart.upload_id, parts: upload.multipart.parts.map((part) => ({ part_number: part.part_number, etag: `mock-etag-${part.part_number}` })) }
        : { etag: 'mock-etag', parts: [] }
    },
  }
}
