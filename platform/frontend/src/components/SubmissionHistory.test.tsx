import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { SubmissionHistory } from './SubmissionHistory'

const { getSubmissions } = vi.hoisted(() => ({ getSubmissions: vi.fn() }))
vi.mock('../api/context', () => ({ useApi: () => ({ getSubmissions }) }))
afterEach(() => { cleanup(); getSubmissions.mockReset() })

it('loads only when expanded and preserves earlier records across a failed next page', async () => {
  const row = { upload_id: 'upl-a', label: 'version-a', batch: 'batch-a', source: 'QA', filename: 'test.dmp', submitted_at: '2026-09-04T00:00:00Z', verified_at: '2026-09-04T00:00:01Z' }
  getSubmissions.mockResolvedValueOnce({ items: [row], next_cursor: 'upl-a' })
    .mockRejectedValueOnce(new Error('temporary'))
    .mockResolvedValueOnce({ items: [{ ...row, upload_id: 'upl-b', label: 'version-b' }], next_cursor: null })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><SubmissionHistory workspaceId="wsp-a" occurrenceId="occ-a" /></QueryClientProvider>)
  expect(getSubmissions).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('提交记录与人工测试标注'))
  await screen.findByText('version-a')
  fireEvent.click(screen.getByText('加载更多提交'))
  await screen.findByText('提交记录暂时无法读取')
  expect(screen.getByText('version-a')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  await screen.findByText('version-b')
  expect(screen.getByText('version-a')).toBeTruthy()
  expect(screen.getByText(/已加载的提交包含不同版本/)).toBeTruthy()
  await waitFor(() => expect(screen.queryByText('加载更多提交')).toBeNull())
  expect(getSubmissions.mock.calls).toEqual([
    ['wsp-a', 'occ-a', undefined], ['wsp-a', 'occ-a', 'upl-a'], ['wsp-a', 'occ-a', 'upl-a'],
  ])
  client.clear()
})
