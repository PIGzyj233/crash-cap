import { createApiClient } from './client'
import type { CanonicalReport, Build, CompleteUploadRequest, CrashGroup, InitUploadResponse, SymbolHealthRow, Workspace, WorkspaceOverview, OccurrenceDetail } from '../types'

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

const frame = (index: number, functionName: string, module: string, trust: 'context' | 'cfi' | 'frame_pointer' | 'scan', inApp = true) => ({
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

const canonical: CanonicalReport = {
  schema_version: '1.0',
  workspace_id: workspace.id,
  occurrence_id: 'occ_demo',
  analysis_id: 'run_demo',
  engine: {
    core_version: 'dmp-core 1.0.0',
    core_image_digest: 'sha256:' + 'a'.repeat(64),
    symbolicator_version: 'symbolicator 24.7',
    grouping_version: 'group-v1.0',
    normalization_version: 'norm-v1.0',
  },
  build_resolution: {
    reported_build_id: 'bld_240821',
    resolved_build_id: 'bld_240821',
    resolution_method: 'auto_unique',
    evidence: {
      candidate_build_ids: ['bld_240821'],
      matched_entrypoints: ['desktop-client.exe'],
      matched_owned_modules: ['render.dll'],
      conflicting_modules: [],
      note: null,
    },
  },
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
    { code_file: 'desktop-client.exe', debug_file: 'desktop-client.pdb', code_id: '67A1B9231F000', debug_id: 'b0c27c20a4704c4fa6f2b706d29f7e031', image_base: '0x140000000', image_size: 12_582_912, role: 'entrypoint', in_app: true, artifact_ids: ['art_app_pe', 'art_app_pdb'], status: 'matched' },
    { code_file: 'render.dll', debug_file: 'render.pdb', code_id: '67A1B925A1000', debug_id: '94e72158e9a3443c787b78a8a3448d0d730', image_base: '0x180000000', image_size: 4_194_304, role: 'owned', in_app: true, artifact_ids: ['art_render_pe', 'art_render_pdb'], status: 'matched' },
    { code_file: 'ucrtbase.dll', debug_file: null, code_id: null, debug_id: null, image_base: null, image_size: null, role: 'system', in_app: false, artifact_ids: [], status: 'system_symbol_pending' },
  ],
  quality: {
    score: 0.91,
    symbol_coverage: 0.93,
    unwind_reliability: 0.9,
    artifact_completeness: 0.88,
    warnings: [
      { code: 'system_symbol_pending', message: '系统模块 ucrtbase.dll 缺少符号；业务栈仍可用。', module: 'ucrtbase.dll', debug_id: null },
      { code: 'scan_frames', message: '线程 7 的第 4 帧由 scan unwind 得到，标记为低可信。', module: 'kernel32.dll', debug_id: null },
    ],
  },
  fingerprints: { exact: 'e'.repeat(64), family: null, algorithm: 'exact-v1.0' },
}

const primaryGroup: Build['groups'][number] = {
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
  first_build_id: 'bld_240819',
  last_build_id: 'bld_240821',
}

const build: Build = {
  id: 'bld_240821',
  workspace_id: workspace.id,
  version: '2026.08.21.1',
  build_number: '240821-1',
  commit_sha: 'a1c9f04f5d7a',
  channel: 'stable',
  architecture: 'x86_64',
  toolchain: 'msvc-19.40',
  producer: 'msvc',
  producer_build_id: 'pipeline-240821-1',
  manifest_object_key: 'raw-builds/wsp_demo/bld_240821/manifest.json',
  manifest_schema_version: '2.0',
  source_bundle_config: { schema_version: '1.0', archive: 'source-bundle.zip', source_root: 'C:/agent/_work/product', context_lines: 3 },
  created_at: iso(60 * 9),
  modules: [
    { id: 'mod_app', code_file: 'desktop-client.exe', debug_file: 'desktop-client.pdb', role: 'entrypoint', code_id: '67A1B9231F000', debug_id: 'b0c27c20a4704c4fa6f2b706d29f7e031', in_app: true, artifact_count: 2, missing_occurrence_count: 0 },
    { id: 'mod_render', code_file: 'render.dll', debug_file: 'render.pdb', role: 'owned', code_id: '67A1B925A1000', debug_id: '94e72158e9a3443c787b78a8a3448d0d730', in_app: true, artifact_count: 2, missing_occurrence_count: 0 },
    { id: 'mod_ucrt', code_file: 'ucrtbase.dll', debug_file: 'ucrtbase.pdb', role: 'dependency', code_id: null, debug_id: null, in_app: false, artifact_count: 0, missing_occurrence_count: 17 },
  ],
  artifacts: [
    { id: 'art_app_pe', module_id: 'mod_app', kind: 'pe', logical_name: 'desktop-client.exe', sha256: '1'.repeat(64), size: 8_420_112, code_id: '67A1B9231F000', debug_id: 'b0c27c20a4704c4fa6f2b706d29f7e031', verification_status: 'verified', ingest_metadata: null, created_at: iso(60 * 8) },
    { id: 'art_app_pdb', module_id: 'mod_app', kind: 'pdb', logical_name: 'desktop-client.pdb', sha256: '2'.repeat(64), size: 41_900_112, code_id: null, debug_id: 'b0c27c20a4704c4fa6f2b706d29f7e031', verification_status: 'verified', ingest_metadata: null, created_at: iso(60 * 8) },
    { id: 'art_render_pe', module_id: 'mod_render', kind: 'pe', logical_name: 'render.dll', sha256: '3'.repeat(64), size: 3_120_112, code_id: '67A1B925A1000', debug_id: '94e72158e9a3443c787b78a8a3448d0d730', verification_status: 'verified', ingest_metadata: null, created_at: iso(60 * 8) },
    { id: 'art_render_bad_pdb', module_id: 'mod_render', kind: 'pdb', logical_name: 'render.pdb', sha256: '4'.repeat(64), size: 22_012_882, code_id: null, debug_id: '94e72158e9a3443c787b78a8a3448d0d730', verification_status: 'pdb_mismatch', ingest_metadata: null, created_at: iso(60 * 7) },
  ],
  groups: [primaryGroup],
}

const overview: WorkspaceOverview = {
  window_start: iso(60 * 24 * 7),
  window_end: now.toISOString(),
  crash_occurrences: 128,
  exact_groups: 14,
  unclassified: 19,
  versions: [{ version: '2026.08.21.1', count: 45 }, { version: '2026.08.20.3', count: 38 }, { version: '2026.08.19.8', count: 26 }, { version: null, count: 19 }],
  top_groups: [build.groups[0], { ...primaryGroup, id: 'grp_2', title: 'EXCEPTION_ILLEGAL_INSTRUCTION · Cpu::Dispatch', fingerprint: 'f'.repeat(64), occurrence_count: 14, status: 'investigating', first_seen: iso(60 * 24 * 5), last_seen: iso(60 * 50) }],
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
  reported_build_id: build.id,
  dump_timestamp: iso(20),
  reported_at: null,
  occurred_at: iso(20),
  uploaded_at: iso(18),
  time_source: 'dump',
  current_analysis: { id: 'run_demo', status: 'COMPLETE', resolution_method: 'auto_unique', resolved_build_id: build.id, quality_score: canonical.quality.score, started_at: iso(17), finished_at: iso(16), duration_ms: 42_800, error_code: null },
  latest_attempt: { id: 'run_demo', status: 'COMPLETE', resolution_method: 'auto_unique', resolved_build_id: build.id, quality_score: canonical.quality.score, started_at: iso(17), finished_at: iso(16), duration_ms: 42_800, error_code: null },
  group: build.groups[0],
}

const groups: CrashGroup[] = [{
  id: 'grp_demo', workspace_id: workspace.id, group_type: 'exact', fingerprint: 'e'.repeat(64), title: 'EXCEPTION_ACCESS_VIOLATION · Renderer::SubmitFrame', status: 'open', owner: null, issue_url: null, first_seen: iso(60 * 24 * 7), last_seen: iso(20), occurrence_count: 23, first_build_id: 'bld_240819', last_build_id: build.id, representative_stack: canonical.threads[0].frames.slice(0, 3), build_distribution: [{ build_id: build.id, version: build.version, count: 18 }, { build_id: 'bld_240819', version: '2026.08.19.8', count: 5 }], occurrence_ids: ['occ_demo'],
}]

const symbols: SymbolHealthRow[] = [
  { build_id: build.id, module_id: 'mod_app', code_file: 'desktop-client.exe', debug_file: 'desktop-client.pdb', code_id: '67A1B9231F000', debug_id: canonical.crash.fault_module_debug_id ?? null, status: 'matched', affected_occurrence_count: 0, first_seen: iso(60 * 24 * 30), last_seen: iso(20), occurrence_ids: [] },
  { build_id: build.id, module_id: 'mod_render', code_file: 'render.dll', debug_file: 'render.pdb', code_id: '67A1B925A1000', debug_id: '94e72158e9a3443c787b78a8a3448d0d730', status: 'matched', affected_occurrence_count: 0, first_seen: iso(60 * 24 * 30), last_seen: iso(20), occurrence_ids: [] },
  { build_id: build.id, module_id: 'mod_ucrt', code_file: 'ucrtbase.dll', debug_file: null, code_id: null, debug_id: null, status: 'missing', affected_occurrence_count: 17, first_seen: iso(60 * 24 * 10), last_seen: iso(60), occurrence_ids: ['occ_demo'] },
  { build_id: build.id, module_id: 'mod_render', code_file: 'render.dll', debug_file: 'render.pdb', code_id: 'old', debug_id: 'old-debug-id', status: 'mismatch', affected_occurrence_count: 2, first_seen: iso(60 * 24 * 2), last_seen: iso(60 * 3), occurrence_ids: ['occ_demo'] },
]

function jsonResponse(data: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' }, ...init })
}

export function createMockApiClient() {
  let pollCount = 0
  const uploadPollCounts = new Map<string, number>()
  const mockFetch: typeof fetch = async (input, init) => {
    const rawUrl = typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString()
    if (rawUrl.startsWith('http://rustfs.local/')) return new Response(null, { status: 200 })
    const url = new URL(rawUrl, 'http://crash-cap.local')
    const path = url.pathname.replace(/^\/api\/v1/, '')
    const method = init?.method ?? 'GET'

    if (method === 'GET' && path === '/workspaces') return jsonResponse([workspace])
    if (method === 'GET' && path === `/workspaces/${workspace.id}`) return jsonResponse(workspace)
    if (method === 'GET' && path === `/workspaces/${workspace.id}/overview`) return jsonResponse(overview)
    if (method === 'GET' && path === `/workspaces/${workspace.id}/builds`) return jsonResponse([build])
    if (method === 'GET' && path === `/builds/${build.id}`) return jsonResponse(build)
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
    if (method === 'GET' && path === `/occurrences/${occurrence.id}/analysis`) return jsonResponse(canonical)
    if (method === 'GET' && path === `/occurrences/${occurrence.id}/threads`) return jsonResponse(canonical.threads)
    if (method === 'GET' && path === `/occurrences/${occurrence.id}/modules`) return jsonResponse(canonical.modules)
    if (method === 'POST' && path === `/occurrences/${occurrence.id}/reprocess`) return jsonResponse({ ...occurrence.latest_attempt, id: 'run_reprocess', status: 'QUEUED', created: true })
    if (method === 'POST' && path === '/workspaces') return jsonResponse(workspace, { status: 201 })
    if (method === 'POST' && path === `/workspaces/${workspace.id}/builds`) return jsonResponse(build, { status: 201 })
    if (method === 'PUT' && path === `/builds/${build.id}/manifest`) return jsonResponse(build)
    if (method === 'POST' && path === `/builds/${build.id}/artifacts/uploads:init`) return jsonResponse({ upload_id: 'upl_artifact', method: 'PUT', url: 'http://rustfs.local/artifact', headers: {}, expires_in: 900 })
    if (method === 'POST' && path === `/workspaces/${workspace.id}/dumps/uploads:init`) return jsonResponse({ upload_id: 'upl_dump', method: 'PUT', url: 'http://rustfs.local/dump', headers: {}, expires_in: 900 })
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
    if (method === 'POST' && /^\/uploads\/[^/]+\/complete$/.test(path)) {
      return jsonResponse({ upload_id: path.split('/')[2], status: 'VERIFYING', verification_status: 'VERIFYING' })
    }
    return jsonResponse({ error: { code: 'NOT_FOUND', message: 'Mock route not found' } }, { status: 404 })
  }
  const api = createApiClient({ baseUrl: '/api/v1', fetcher: mockFetch, rawDownloadEnabled: false })
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
