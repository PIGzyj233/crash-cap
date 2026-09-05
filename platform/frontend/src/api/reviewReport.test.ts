import { createHash } from 'node:crypto'
import { expect, it, vi } from 'vitest'
import { createApiClient } from './client'
import { readReviewReport } from './reviewReport'

it('binds the raw report bytes including whitespace and split UTF-8 sequences', async () => {
  const text = '{\n "schema_version":"2.0", "analysis_id":"run", "occurrence_id":"occ", "note":"原报告"\n}\n'
  const bytes = new TextEncoder().encode(text)
  let offset = 0
  const response = new Response(new ReadableStream({ pull(controller) {
    if (offset === bytes.length) controller.close()
    else controller.enqueue(bytes.slice(offset, ++offset))
  } }))
  const result = await readReviewReport(response, 'occ', 'run')
  expect(result.sha256).toBe(createHash('sha256').update(bytes).digest('hex'))
  expect(result.sha256).not.toBe(createHash('sha256').update(JSON.stringify(result.report)).digest('hex'))
})

it.each([
  { schema_version: '2.0', analysis_id: 'other', occurrence_id: 'occ' },
  { schema_version: '2.0', analysis_id: 'run', occurrence_id: 'other' },
  { schema_version: '9.0', analysis_id: 'run', occurrence_id: 'occ' },
])('rejects a substituted report', async (report) => {
  await expect(readReviewReport(new Response(JSON.stringify(report)), 'occ', 'run')).rejects.toThrow('报告身份或版本不匹配')
})

it('cancels an oversized response stream', async () => {
  const cancel = vi.fn()
  const chunk = new Uint8Array(1024 * 1024)
  const response = new Response(new ReadableStream({ pull(controller) { controller.enqueue(chunk) }, cancel }))
  await expect(readReviewReport(response, 'occ', 'run')).rejects.toThrow('报告超过审核读取上限')
  expect(cancel).toHaveBeenCalledOnce()
})

it('uses the explicit run route and propagates structured API errors', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'NOT_FOUND', message: 'missing' } }), { status: 404 }))
  const api = createApiClient({ baseUrl: '/api/v3', fetcher })
  await expect(api.getReviewReport('occ/a', 'run/b')).rejects.toMatchObject({ status: 404, code: 'NOT_FOUND' })
  expect(fetcher).toHaveBeenCalledWith('/api/v3/occurrences/occ%2Fa/analysis?run_id=run%2Fb')
})
