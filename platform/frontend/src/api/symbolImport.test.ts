import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from './client'

describe('independent symbol import transport', () => {
  it('uploads raw bytes and completes one item without a Build or Workspace', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => new Response('{}', { status: 200 }))
    const api = createApiClient({ baseUrl: '/legacy', analysisBaseUrl: '/reader/v2', fetcher })
    const file = new File([new Uint8Array([77, 90, 0, 255])], 'engine.dll')
    const claim = { name: file.name, raw_sha256: 'a'.repeat(64), raw_size: file.size }
    const batch = { idempotency_key: 'once', source_label: 'QA build folder', pairs: [{ client_pair_id: 'pair-a', pe: claim, pdb: { ...claim, name: 'engine.pdb' } }] }
    await api.createSymbolImport(batch)
    await api.uploadSymbolImportFile('import/a', 'item/b', 'pe', file)
    await api.completeSymbolImportItem('import/a', 'item/b')
    await api.getSymbolImport('import/a')
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      '/reader/v2/symbol-imports',
      '/reader/v2/symbol-imports/import%2Fa/items/item%2Fb/files/pe',
      '/reader/v2/symbol-imports/import%2Fa/items/item%2Fb/complete',
      '/reader/v2/symbol-imports/import%2Fa',
    ])
    expect(fetcher.mock.calls[0][1]?.body).toBe(JSON.stringify(batch))
    const upload = fetcher.mock.calls[1][1]!
    expect(upload.body).toBe(file)
    expect(upload.method).toBe('PUT')
    expect(new Headers(upload.headers).get('Content-Type')).toBe('application/octet-stream')
    expect(fetcher.mock.calls[2][1]?.method).toBe('POST')
  })
})
