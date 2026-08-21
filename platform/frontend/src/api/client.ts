import type {
  ApiClientOptions,
  ApiErrorBody,
  Build,
  BuildCreateInput,
  BuildManifestInput,
  CaptureProfile,
  CompleteUploadRequest,
  CompleteUploadResponse,
  CrashGroupSummary,
  InitUploadResponse,
  OccurrenceDetail,
  PresignedDownload,
  RawDownloadState,
  ReprocessResponse,
  SymbolHealthRow,
  Workspace,
  WorkspaceOverview,
  CrashGroup,
} from '../types'

export class CrashCapApiError extends Error {
  readonly status: number
  readonly code: string | undefined
  readonly requestId: string | undefined

  constructor(message: string, status: number, body?: ApiErrorBody, requestId?: string) {
    super(message)
    this.name = 'CrashCapApiError'
    this.status = status
    this.code = body?.error?.code
    this.requestId = requestId ?? body?.error?.request_id
  }
}

function joinUrl(baseUrl: string, path: string): string {
  const cleanBase = baseUrl.replace(/\/$/, '')
  return `${cleanBase}/${path.replace(/^\//, '')}`
}

async function readError(response: Response): Promise<CrashCapApiError> {
  let body: ApiErrorBody | undefined
  try {
    body = (await response.json()) as ApiErrorBody
  } catch {
    // The API may return a gateway text body. Do not expose it verbatim.
  }
  return new CrashCapApiError(
    body?.error?.message ?? `Crash-Cap API request failed (${response.status})`,
    response.status,
    body,
    response.headers.get('X-Request-ID') ?? undefined,
  )
}

const MULTIPART_PART_SIZE = 64 * 1024 * 1024

async function uploadObject(
  fetcher: typeof fetch,
  url: string,
  method: 'PUT' | 'POST',
  headers: Record<string, string>,
  body: Blob,
  onProgress?: (loaded: number, total: number) => void,
): Promise<string | undefined> {
  if (!onProgress) {
    const response = await fetcher(url, { method, headers, body })
    if (!response.ok) throw await readError(response)
    return response.headers.get('ETag') ?? response.headers.get('etag') ?? undefined
  }

  return new Promise<string | undefined>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(method, url)
    Object.entries(headers).forEach(([key, value]) => xhr.setRequestHeader(key, value))
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded, event.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.getResponseHeader('ETag') ?? xhr.getResponseHeader('etag') ?? undefined)
      } else {
        reject(new CrashCapApiError('对象存储上传失败', xhr.status))
      }
    }
    xhr.onerror = () => reject(new CrashCapApiError('对象存储上传网络错误', 0))
    xhr.send(body)
  })
}

export interface UploadPollingOptions {
  intervalMs?: number
  maxAttempts?: number
}

export function isUploadTerminalStatus(status: string | undefined): boolean {
  return status ? ['ACCEPTED', 'REJECTED', 'QUARANTINED'].includes(status.toUpperCase()) : false
}

export async function waitForUploadStatus(
  fetchStatus: () => Promise<CompleteUploadResponse>,
  options: UploadPollingOptions = {},
): Promise<CompleteUploadResponse> {
  const intervalMs = options.intervalMs ?? 1_000
  const maxAttempts = options.maxAttempts ?? 120
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const status = await fetchStatus()
    if (isUploadTerminalStatus(status.status ?? status.verification_status)) return status
    if (attempt < maxAttempts - 1 && intervalMs > 0) {
      await new Promise<void>((resolve) => setTimeout(resolve, intervalMs))
    }
  }
  throw new CrashCapApiError('上传验证超时，请稍后在列表中查看状态', 408)
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? '/api/v1'
  const fetcher = options.fetcher ?? fetch
  const rawDownloadEnabled = options.rawDownloadEnabled ?? import.meta.env.VITE_RAW_DOWNLOAD_ENABLED === 'true'

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers)
    if (init?.body && !headers.has('Content-Type') && !(init.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json')
    }
    const response = await fetcher(joinUrl(baseUrl, path), { ...init, headers })
    if (!response.ok) throw await readError(response)
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }

  async function uploadPresigned(upload: InitUploadResponse, file: File, onProgress?: (percent: number) => void): Promise<CompleteUploadRequest> {
    if (!upload.multipart) {
      const etag = await uploadObject(
        fetcher,
        upload.url,
        upload.method,
        upload.headers,
        file,
        onProgress
          ? (loaded, total) => onProgress(total ? Math.round((loaded / total) * 100) : 0)
          : undefined,
      )
      return { ...(etag ? { etag } : {}), parts: [] }
    }

    if (upload.multipart.parts.length === 0) {
      throw new CrashCapApiError('对象存储未返回可上传的 multipart 分片', 502)
    }

    let uploadedBytes = 0
    const parts: CompleteUploadRequest['parts'] = []
    for (const [index, part] of upload.multipart.parts.entries()) {
      const start = index * MULTIPART_PART_SIZE
      const end = Math.min(file.size, start + MULTIPART_PART_SIZE)
      if (start >= file.size || end <= start) {
        throw new CrashCapApiError('multipart 分片数量与文件大小不匹配', 502)
      }
      const partSize = end - start
      const etag = await uploadObject(
        fetcher,
        part.url,
        upload.method,
        upload.headers,
        file.slice(start, end),
        onProgress
          ? (loaded) => onProgress(Math.round(((uploadedBytes + loaded) / file.size) * 100))
          : undefined,
      )
      if (!etag) throw new CrashCapApiError(`multipart 第 ${part.part_number} 片缺少 ETag`, 502)
      parts.push({ part_number: part.part_number, etag })
      uploadedBytes += partSize
    }
    return { multipart_upload_id: upload.multipart.upload_id, parts }
  }

  return {
    baseUrl,
    rawDownloadEnabled,
    listWorkspaces: () => request<Workspace[]>('/workspaces'),
    getWorkspace: (workspaceId: string) => request<Workspace>(`/workspaces/${encodeURIComponent(workspaceId)}`),
    createWorkspace: (input: { name: string; display_name?: string; retention_days?: number }) =>
      request<Workspace>('/workspaces', { method: 'POST', body: JSON.stringify(input) }),
    getWorkspaceOverview: (workspaceId: string, params?: { from?: string; to?: string }) => {
      const query = new URLSearchParams()
      if (params?.from) query.set('from', params.from)
      if (params?.to) query.set('to', params.to)
      return request<WorkspaceOverview>(`/workspaces/${encodeURIComponent(workspaceId)}/overview?${query}`)
    },
    listBuilds: (workspaceId: string, params?: { version?: string }) => {
      const query = new URLSearchParams()
      if (params?.version) query.set('version', params.version)
      return request<Build[]>(`/workspaces/${encodeURIComponent(workspaceId)}/builds?${query}`)
    },
    getBuild: (buildId: string) => request<Build>(`/builds/${encodeURIComponent(buildId)}`),
    createBuild: (
      workspaceId: string,
      input: BuildCreateInput,
    ) => request<Build>(`/workspaces/${encodeURIComponent(workspaceId)}/builds`, { method: 'POST', body: JSON.stringify(input) }),
    putManifest: (buildId: string, manifest: BuildManifestInput) =>
      request<Build>(`/builds/${encodeURIComponent(buildId)}/manifest`, { method: 'PUT', body: JSON.stringify(manifest) }),
    initArtifactUpload: (buildId: string, input: { file_kind: 'pe' | 'pdb' | 'source_bundle'; filename: string; size: number; sha256?: string }) =>
      request<InitUploadResponse>(`/builds/${encodeURIComponent(buildId)}/artifacts/uploads:init`, { method: 'POST', body: JSON.stringify(input) }),
    completeUpload: (uploadId: string, body: CompleteUploadRequest = { parts: [] }) =>
      request<CompleteUploadResponse>(`/uploads/${encodeURIComponent(uploadId)}/complete`, { method: 'POST', body: JSON.stringify(body) }),
    getUpload: (uploadId: string) => request<CompleteUploadResponse>(`/uploads/${encodeURIComponent(uploadId)}`),
    waitForUpload: (uploadId: string, pollingOptions?: UploadPollingOptions) =>
      waitForUploadStatus(() => request<CompleteUploadResponse>(`/uploads/${encodeURIComponent(uploadId)}`), pollingOptions),
    initDumpUpload: (workspaceId: string, input: { filename: string; size: number; sha256?: string; capture_profile?: CaptureProfile; reported_build_id?: string; reported_at?: string }) =>
      request<InitUploadResponse>(`/workspaces/${encodeURIComponent(workspaceId)}/dumps/uploads:init`, { method: 'POST', body: JSON.stringify(input) }),
    getOccurrence: (occurrenceId: string) => request<OccurrenceDetail>(`/occurrences/${encodeURIComponent(occurrenceId)}`),
    getOccurrenceAnalysis: (occurrenceId: string, runId?: string) => {
      const query = runId ? `?run_id=${encodeURIComponent(runId)}` : ''
      return request<import('../types').CanonicalReport>(`/occurrences/${encodeURIComponent(occurrenceId)}/analysis${query}`)
    },
    getOccurrenceThreads: (occurrenceId: string, runId?: string) => {
      const query = runId ? `?run_id=${encodeURIComponent(runId)}` : ''
      return request<import('../types').Thread[]>(`/occurrences/${encodeURIComponent(occurrenceId)}/threads${query}`)
    },
    getOccurrenceModules: (occurrenceId: string, runId?: string) => {
      const query = runId ? `?run_id=${encodeURIComponent(runId)}` : ''
      return request<import('../types').AnalysisModule[]>(`/occurrences/${encodeURIComponent(occurrenceId)}/modules${query}`)
    },
    reprocessOccurrence: (occurrenceId: string, body: { force: boolean; reported_build_id?: string } = { force: false }) =>
      request<ReprocessResponse>(`/occurrences/${encodeURIComponent(occurrenceId)}/reprocess`, { method: 'POST', body: JSON.stringify(body) }),
    listGroups: (workspaceId: string, params?: { status?: string; group_type?: string; q?: string }) => {
      const query = new URLSearchParams()
      if (params?.status) query.set('status', params.status)
      if (params?.group_type) query.set('group_type', params.group_type)
      if (params?.q) query.set('q', params.q)
      return request<CrashGroupSummary[]>(`/workspaces/${encodeURIComponent(workspaceId)}/groups?${query}`)
    },
    getGroup: (groupId: string) => request<CrashGroup>(`/groups/${encodeURIComponent(groupId)}`),
    updateGroup: (groupId: string, patch: { status?: string; owner?: string; issue_url?: string; title?: string }) =>
      request<CrashGroup>(`/groups/${encodeURIComponent(groupId)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    getSymbolHealth: (workspaceId: string) => request<SymbolHealthRow[]>(`/workspaces/${encodeURIComponent(workspaceId)}/symbols/health`),
    getMissingSymbols: (workspaceId: string) => request<SymbolHealthRow[]>(`/workspaces/${encodeURIComponent(workspaceId)}/symbols/missing`),
    getRawDownloadState: (): RawDownloadState => ({ enabled: rawDownloadEnabled, reason: rawDownloadEnabled ? undefined : 'RAW_DOWNLOAD_DISABLED' }),
    getRawDownload: async (occurrenceId: string) => {
      if (!rawDownloadEnabled) throw new CrashCapApiError('原始二进制下载已由部署开关禁用', 403, { error: { code: 'RAW_DOWNLOAD_DISABLED' } })
      return request<PresignedDownload>(`/occurrences/${encodeURIComponent(occurrenceId)}/download`)
    },
    getArtifactDownload: async (artifactId: string) => {
      if (!rawDownloadEnabled) throw new CrashCapApiError('原始二进制下载已由部署开关禁用', 403, { error: { code: 'RAW_DOWNLOAD_DISABLED' } })
      return request<PresignedDownload>(`/artifacts/${encodeURIComponent(artifactId)}/download`)
    },
    uploadPresigned,
  }
}

export type CrashCapApi = ReturnType<typeof createApiClient>
