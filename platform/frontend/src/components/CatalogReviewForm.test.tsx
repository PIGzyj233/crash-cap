import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { CatalogReviewForm } from './CatalogReviewForm'

const { submitCatalogReview, capability } = vi.hoisted(() => ({ submitCatalogReview: vi.fn(), capability: { enabled: true } }))
vi.mock('../api/context', () => ({ useApi: () => ({ submitCatalogReview }) }))
vi.mock('../api/hooks', () => ({ useCapabilities: () => ({ data: { enabled_writes: capability.enabled ? ['catalog_reviews'] : [] } }) }))
afterEach(() => { cleanup(); vi.restoreAllMocks(); sessionStorage.clear(); submitCatalogReview.mockReset(); capability.enabled = true })

it('keeps the exact version and idempotency key after an uncertain response', async () => {
  submitCatalogReview.mockRejectedValueOnce(new Error('connection lost')).mockResolvedValueOnce({ id: 'review-a' })
  const saved = vi.fn()
  const view = render(<CatalogReviewForm pairId="pair-a" version={7} onSaved={saved} />)
  fireEvent.change(screen.getByRole('textbox', { name: '复核人' }), { target: { value: 'Provider' } })
  fireEvent.change(screen.getByRole('textbox', { name: '复核原因' }), { target: { value: 'Wrong artifact' } })
  fireEvent.change(screen.getByRole('textbox', { name: '复核依据' }), { target: { value: 'Compared original build output and checked hashes' } })
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByText('提交复核结论'))
  await screen.findByText('connection lost')
  view.unmount()
  render(<CatalogReviewForm pairId="pair-a" version={8} onSaved={saved} />)
  expect(screen.getByText('已恢复尚未确认结果的复核请求。')).toBeTruthy()
  expect((screen.getByRole('textbox', { name: '复核依据' }) as HTMLTextAreaElement).disabled).toBe(true)
  fireEvent.click(screen.getByText('重试相同复核'))
  await waitFor(() => expect(saved).toHaveBeenCalledTimes(1))
  expect(submitCatalogReview.mock.calls[0]).toEqual(submitCatalogReview.mock.calls[1])
  expect(submitCatalogReview.mock.calls[0][1].expected_version).toBe(7)
  expect(submitCatalogReview.mock.calls[0][1].idempotency_key).toBeTruthy()
  expect(sessionStorage.length).toBe(0)
})

it('warns when tab storage is unavailable and still keeps the in-memory request', async () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
  submitCatalogReview.mockRejectedValue(new Error('connection lost'))
  render(<CatalogReviewForm pairId="pair-b" version={2} onSaved={() => {}} />)
  for (const name of ['复核人', '复核原因', '复核依据']) fireEvent.change(screen.getByRole('textbox', { name }), { target: { value: 'Verified' } })
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByText('提交复核结论'))
  await screen.findByText('connection lost')
  expect(screen.getByText('无法在本标签页暂存请求；结果确认前请勿刷新页面。')).toBeTruthy()
  fireEvent.click(screen.getByText('重试相同复核'))
  await waitFor(() => expect(submitCatalogReview).toHaveBeenCalledTimes(2))
  expect(submitCatalogReview.mock.calls[0]).toEqual(submitCatalogReview.mock.calls[1])
})

it('blocks writes when the review capability is unavailable', () => {
  capability.enabled = false
  render(<CatalogReviewForm pairId="pair-a" version={7} onSaved={() => {}} />)
  expect((screen.getByRole('button', { name: '提交复核结论' }) as HTMLButtonElement).disabled).toBe(true)
  expect(submitCatalogReview).not.toHaveBeenCalled()
})
