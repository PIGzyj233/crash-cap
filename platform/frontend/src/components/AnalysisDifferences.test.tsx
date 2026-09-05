import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AnalysisDifferences } from './AnalysisDifferences'

const { getAnalysisDifferences } = vi.hoisted(() => ({ getAnalysisDifferences: vi.fn() }))
vi.mock('../api/context', () => ({ useApi: () => ({ getAnalysisDifferences }) }))
afterEach(() => { cleanup(); getAnalysisDifferences.mockReset() })

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><AnalysisDifferences workspaceId="w" occurrenceId="o" runId="r" /></QueryClientProvider>)
  return client
}

it('does not describe a failed initial read as an empty recorded difference list', async () => {
  getAnalysisDifferences.mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce({ items: [], next_offset: null, total: 0 })
  const client = show()
  expect(getAnalysisDifferences).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('查看证据差异'))
  await screen.findByText('证据差异暂时无法读取')
  expect(screen.queryByText('该次决策未记录逐项差异')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  await screen.findByText('该次决策未记录逐项差异')
  expect(getAnalysisDifferences.mock.calls).toEqual([['w', 'o', 'r', 0], ['w', 'o', 'r', 0]])
  client.clear()
})

it('preserves values and earlier pages while retrying a later offset', async () => {
  getAnalysisDifferences.mockResolvedValueOnce({ items: [{ path: 'first', before: null, after: 0 }], next_offset: 1, total: 2 })
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce({ items: [{ path: 'second', before: false, after: { function: 'new-name' } }], next_offset: null, total: 2 })
  const client = show()
  fireEvent.click(screen.getByText('查看证据差异'))
  await screen.findByText('first')
  expect(screen.getByText('无')).toBeTruthy()
  expect(screen.getByText('0')).toBeTruthy()
  fireEvent.click(screen.getByText('加载更多差异'))
  await screen.findByText('证据差异暂时无法读取')
  expect(screen.getByText('first')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  await screen.findByText('second')
  expect(screen.getByText('false')).toBeTruthy()
  expect(screen.getByText(/new-name/)).toBeTruthy()
  expect(getAnalysisDifferences.mock.calls).toEqual([['w', 'o', 'r', 0], ['w', 'o', 'r', 1], ['w', 'o', 'r', 1]])
  client.clear()
})
