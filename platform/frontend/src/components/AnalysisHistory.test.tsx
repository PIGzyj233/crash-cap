import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { AnalysisHistory } from './AnalysisHistory'

const { getAnalysisHistory } = vi.hoisted(() => ({ getAnalysisHistory: vi.fn() }))
vi.mock('../api/context', () => ({ useApi: () => ({ getAnalysisHistory }) }))
afterEach(() => { cleanup(); getAnalysisHistory.mockReset() })

it('separates a retained candidate from Current and links to the original report', async () => {
  getAnalysisHistory.mockResolvedValue({ current_run_id: 'run-old', next_cursor: null, items: [
    { id: 'run-new', status: 'PARTIAL', report_available: true, finished_at: '2026-09-04T00:00:00Z', selection: { decision: 'retain', reason: 'permanent_loss', observed_current_run_id: 'run-old' } },
    { id: 'run-old', status: 'PARTIAL', report_available: true, finished_at: null, selection: null },
  ] })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><AnalysisHistory workspaceId="w" occurrenceId="o" /></MemoryRouter></QueryClientProvider>)
  expect(getAnalysisHistory).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('分析历史与报告选择依据'))
  await screen.findByText('保留原报告：已有证据永久缺失')
  expect(screen.getByText('Current').closest('tr')?.textContent).toContain('run-old')
  expect(screen.getByText('查看当时的原报告').getAttribute('href')).toBe('/w/w/occurrences/o?run=run-old')
  expect(screen.getByText('run-new').getAttribute('href')).toBe('/w/w/occurrences/o?run=run-new')
  expect(screen.getByText('未记录选择依据')).toBeTruthy()
  client.clear()
})

it('preserves loaded reports when a later page fails and retries that cursor', async () => {
  const first = { id: 'run-c', status: 'PARTIAL', report_available: true, finished_at: null, selection: null }
  getAnalysisHistory.mockResolvedValueOnce({ current_run_id: 'run-c', next_cursor: 'run-c', items: [first] })
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce({ current_run_id: 'run-c', next_cursor: null, items: [{ ...first, id: 'run-b', status: 'QUEUED', report_available: false }] })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><AnalysisHistory workspaceId="w" occurrenceId="o" /></MemoryRouter></QueryClientProvider>)
  fireEvent.click(screen.getByText('分析历史与报告选择依据'))
  await screen.findByText('run-c')
  fireEvent.click(screen.getByText('加载更多分析'))
  await screen.findByText('分析历史暂时无法读取')
  expect(screen.getByText('run-c').getAttribute('href')).toContain('run=run-c')
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  await screen.findByText('run-b')
  expect(screen.getByText('run-b').closest('a')).toBeNull()
  expect(getAnalysisHistory.mock.calls.slice(0, 3)).toEqual([
    ['w', 'o', undefined], ['w', 'o', 'run-c'], ['w', 'o', 'run-c'],
  ])
  client.clear()
})
