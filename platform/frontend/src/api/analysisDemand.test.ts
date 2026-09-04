import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from './client'
import { demandPollingInterval, type AnalysisDemand } from './analysisDemand'

describe('analysis demand reads', () => {
  it('uses the configured reader and escapes both scope identifiers', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('null', { status: 200 }))
    const api = createApiClient({ analysisBaseUrl: '/reader/v2', fetcher })
    await expect(api.getAnalysisDemand('wsp/a', 'occ/b')).resolves.toBeNull()
    expect(fetcher).toHaveBeenCalledWith('/reader/v2/workspaces/wsp%2Fa/occurrences/occ%2Fb/analysis-demand', expect.anything())
  })

  it('keeps checking terminal and absent demands so later symbol changes become visible', () => {
    const demand = { state: 'updated' } as AnalysisDemand
    expect(demandPollingInterval(demand, true, false)).toBe(10_000)
    expect(demandPollingInterval(null, true, false)).toBe(10_000)
    expect(demandPollingInterval({ ...demand, state: 'queued' }, true, false)).toBe(2_000)
    expect(demandPollingInterval(demand, false, false)).toBe(false)
    expect(demandPollingInterval(demand, true, true)).toBe(false)
  })
})
