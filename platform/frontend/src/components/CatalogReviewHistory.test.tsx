import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CatalogReviewHistory } from './CatalogReviewHistory'

const { getCatalogReviews, getCatalogReviewEvidence } = vi.hoisted(() => ({ getCatalogReviews: vi.fn(), getCatalogReviewEvidence: vi.fn() }))
vi.mock('../api/context', () => ({ useApi: () => ({ getCatalogReviews, getCatalogReviewEvidence }) }))
afterEach(() => { cleanup(); getCatalogReviews.mockReset(); getCatalogReviewEvidence.mockReset() })

it('fetches evidence only on request and treats integrity rejection as unavailable', async () => {
  getCatalogReviews.mockResolvedValue({ items: [{ id: 'review-a', state: 'withdrawn', reason: 'Wrong artifact' }], next_version: null })
  getCatalogReviewEvidence.mockRejectedValueOnce(new Error('integrity failed')).mockResolvedValueOnce({ reviewer: 'Provider A', evidence: 'Verified original files' })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><CatalogReviewHistory pairId="pair-a" /></QueryClientProvider>)
  expect(getCatalogReviews).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('已保存的复核记录'))
  await screen.findByText('Wrong artifact')
  expect(getCatalogReviewEvidence).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('查看复核依据'))
  await screen.findByText('依据未能通过读取或校验')
  expect(screen.queryByText(/复核人声明/)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  await screen.findByText('Verified original files')
  expect(screen.getByText('复核人声明：Provider A')).toBeTruthy()
  expect(getCatalogReviewEvidence.mock.calls).toEqual([['pair-a', 'review-a'], ['pair-a', 'review-a']])
  client.clear()
})
