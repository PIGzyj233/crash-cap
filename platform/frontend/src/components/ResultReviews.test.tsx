import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { ResultReviews } from './ResultReviews'

const { getResultReviews, getResultReviewEvidence } = vi.hoisted(() => ({ getResultReviews: vi.fn(), getResultReviewEvidence: vi.fn() }))
vi.mock('../api/context', () => ({ useApi: () => ({ getResultReviews, getResultReviewEvidence }) }))
afterEach(() => { cleanup(); vi.resetAllMocks() })
const row = { id: 'review-1', current_run_id: 'old', candidate_run_id: 'new', decision: 'promote', cause: 'engine_upgrade', created_at: '2026-09-04T00:00:00Z', request: { reviewed_by: 'QA 人工声明', rationale: '已核对两个报告' } }

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><ResultReviews workspaceId="w" occurrenceId="o" /></MemoryRouter></QueryClientProvider>)
  return client
}

it('loads appended decisions separately and reads audit evidence only on request', async () => {
  getResultReviews.mockResolvedValue({ items: [row], next_cursor: null })
  getResultReviewEvidence.mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ created_at: row.created_at, request: { current_canonical_sha256: 'a'.repeat(64), candidate_canonical_sha256: 'b'.repeat(64) }, provider_basis: [] })
  const client = mount()
  expect(getResultReviews).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('查看追加审核记录'))
  await screen.findByText('采用候选报告')
  expect(screen.getByText('查看审核前的报告').getAttribute('href')).toBe('/w/w/occurrences/o?run=old')
  expect(screen.getByText('查看审核候选报告').getAttribute('href')).toBe('/w/w/occurrences/o?run=new')
  expect(screen.getByText('审核人声明：QA 人工声明')).toBeTruthy()
  expect(getResultReviewEvidence).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('查看审核依据'))
  await screen.findByText('审核依据暂时无法读取')
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  await screen.findByText('本次审核未引用提供方复核')
  expect(screen.getByText('a'.repeat(64))).toBeTruthy()
  expect(getResultReviewEvidence).toHaveBeenLastCalledWith('w', 'o', 'review-1')
  client.clear()
})

it('keeps existing reviews and retries the failed pagination cursor', async () => {
  getResultReviews.mockResolvedValueOnce({ items: [row], next_cursor: row.id }).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ items: [{ ...row, id: 'review-0', decision: 'retain', request: { ...row.request, rationale: '较早审核' } }], next_cursor: null })
  const client = mount()
  fireEvent.click(screen.getByText('查看追加审核记录'))
  await screen.findByText('采用候选报告')
  fireEvent.click(screen.getByText('加载更多审核'))
  await screen.findByText('审核记录暂时无法读取')
  expect(screen.getByText('已核对两个报告')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  await screen.findByText('较早审核')
  expect(getResultReviews.mock.calls).toEqual([['w', 'o', undefined], ['w', 'o', 'review-1'], ['w', 'o', 'review-1']])
  client.clear()
})
