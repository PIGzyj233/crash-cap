import { describe, expect, it, vi } from 'vitest'
import { CrashCapApiError, createApiClient } from './client'

describe('configurable /api/v1 client', () => {
  it('uses the configured API prefix and JSON request body', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify([{ id: 'wsp_test' }]), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const api = createApiClient({ baseUrl: 'http://localhost:8000/api/v1/', fetcher })
    await api.listWorkspaces()
    expect(fetcher).toHaveBeenCalledWith('http://localhost:8000/api/v1/workspaces', expect.objectContaining({ headers: expect.any(Headers) }))
  })

  it('does not expose a raw URL when downloads are disabled', async () => {
    const api = createApiClient({ baseUrl: '/api/v1', rawDownloadEnabled: false, fetcher: vi.fn() })
    expect(api.getRawDownloadState()).toEqual({ enabled: false, reason: 'RAW_DOWNLOAD_DISABLED' })
    await expect(api.getRawDownload('occ_test')).rejects.toMatchObject({ code: 'RAW_DOWNLOAD_DISABLED', status: 403 })
    await expect(api.getArtifactDownload('art_test')).rejects.toMatchObject({ code: 'RAW_DOWNLOAD_DISABLED', status: 403 })
  })

  it('requests a PE/PDB artifact presigned URL only when raw downloads are enabled', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ url: 'http://rustfs.local/artifact', expires_at: '2026-08-21T08:05:00Z' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const api = createApiClient({ baseUrl: '/api/v1', rawDownloadEnabled: true, fetcher })
    await expect(api.getArtifactDownload('art/pe')).resolves.toEqual({ url: 'http://rustfs.local/artifact', expires_at: '2026-08-21T08:05:00Z' })
    expect(fetcher).toHaveBeenCalledWith('/api/v1/artifacts/art%2Fpe/download', expect.objectContaining({ headers: expect.any(Headers) }))
  })

  it('preserves API error code and request id without exposing response text', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'DUMP_TOO_LARGE', message: 'Dump exceeds 256 MiB' } }), { status: 413, headers: { 'X-Request-ID': 'req_123' } }))
    const api = createApiClient({ baseUrl: '/api/v1', fetcher })
    await expect(api.listWorkspaces()).rejects.toMatchObject({ code: 'DUMP_TOO_LARGE', requestId: 'req_123', status: 413 })
  })

  it('uploads multipart parts and returns ETags for completion', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 200, headers: { ETag: 'etag-part' } }))
    const api = createApiClient({ baseUrl: '/api/v1', fetcher })
    const file = { size: 64 * 1024 * 1024 + 2, slice: (start: number, end: number) => new Blob([`${start}:${end}`]) } as unknown as File
    const result = await api.uploadPresigned({
      upload_id: 'upl_test', method: 'PUT', url: '', headers: {}, expires_in: 900,
      multipart: { upload_id: 'mp_test', parts: [{ part_number: 1, url: 'http://rustfs.local/part-1' }, { part_number: 2, url: 'http://rustfs.local/part-2' }] },
    }, file)
    expect(result).toEqual({ multipart_upload_id: 'mp_test', parts: [{ part_number: 1, etag: 'etag-part' }, { part_number: 2, etag: 'etag-part' }] })
    expect(fetcher).toHaveBeenNthCalledWith(1, 'http://rustfs.local/part-1', expect.objectContaining({ method: 'PUT' }))
    expect(fetcher).toHaveBeenNthCalledWith(2, 'http://rustfs.local/part-2', expect.objectContaining({ method: 'PUT' }))
  })

  it('sends the multipart completion body', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ upload_id: 'upl_test', status: 'VERIFYING', verification_status: 'VERIFYING' }), { status: 200 }))
    const api = createApiClient({ baseUrl: '/api/v1', fetcher })
    await api.completeUpload('upl_test', { multipart_upload_id: 'mp_test', parts: [{ part_number: 1, etag: 'etag-part' }] })
    expect(fetcher.mock.calls[0]?.[1]).toEqual(expect.objectContaining({ body: JSON.stringify({ multipart_upload_id: 'mp_test', parts: [{ part_number: 1, etag: 'etag-part' }] }) }))
  })

  it('builds an SSE endpoint and submits a targeted batch reprocess', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ workspace_id: 'wsp_test', affected_occurrence_count: 2, created_run_count: 2, occurrence_ids: ['occ_1', 'occ_2'], run_ids: ['run_1', 'run_2'] }), { status: 202 }))
    const api = createApiClient({ baseUrl: 'http://localhost:8000/api/v1', fetcher })
    expect(api.getOccurrenceEventsUrl('occ/1')).toBe('http://localhost:8000/api/v1/occurrences/occ%2F1/events')
    await api.batchReprocessSymbols('wsp_test', { module_id: 'mod_test' })
    expect(fetcher).toHaveBeenCalledWith('http://localhost:8000/api/v1/workspaces/wsp_test/symbols/reprocess', expect.objectContaining({ method: 'POST', body: JSON.stringify({ module_id: 'mod_test' }) }))
  })
})
