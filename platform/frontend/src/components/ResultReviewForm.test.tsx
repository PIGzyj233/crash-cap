import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ResultReviewForm } from './ResultReviewForm'

const { getReviewReport, submitResultReview, capability } = vi.hoisted(() => ({ getReviewReport: vi.fn(), submitResultReview: vi.fn(), capability: { enabled: true } }))
vi.mock('../api/context', () => ({ useApi: () => ({ getReviewReport, submitResultReview }) }))
vi.mock('../api/hooks', () => ({ useCapabilities: () => ({ data: { enabled_writes: capability.enabled ? ['result_reviews'] : [] } }) }))
afterEach(() => { cleanup(); vi.resetAllMocks(); sessionStorage.clear(); capability.enabled = true })

function mount(currentRunId = 'run-1') {
  render(<MemoryRouter><ResultReviewForm workspaceId="w" occurrenceId="o" currentRunId={currentRunId} candidateRunId="run-2" onSaved={vi.fn()} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: /审核此候选报告|确认此前审核结果/ }))
}

it('restores a lost-response request after Current changes without rereading reports', async () => {
  getReviewReport.mockImplementation(async (_occ, run) => ({ report: { schema_version: '1.1', modules: [] }, sha256: (run === 'run-1' ? 'a' : 'b').repeat(64) }))
  submitResultReview.mockRejectedValueOnce(new Error('response lost')).mockResolvedValueOnce({ decision: 'promote' })
  mount()
  fireEvent.click(screen.getByText('读取并绑定两份报告'))
  await screen.findByText('已绑定报告，可查看后填写审核结论。')
  fireEvent.change(screen.getByLabelText('报告审核人'), { target: { value: 'QA' } })
  fireEvent.change(screen.getByLabelText('报告审核说明'), { target: { value: '核对原始报告' } })
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByText('提交报告审核'))
  await screen.findByText('response lost')
  const sent = structuredClone(submitResultReview.mock.calls[0][2])
  expect(sent.current_canonical_sha256).toBe('a'.repeat(64))
  expect(sent.candidate_canonical_sha256).toBe('b'.repeat(64))
  cleanup()
  mount('run-2')
  await screen.findByText('已恢复结果尚未确认的审核请求。')
  fireEvent.click(screen.getByText('重试相同报告审核'))
  await screen.findByText('审核已保存并采用候选报告。')
  expect(submitResultReview.mock.calls[1][2]).toEqual(sent)
  expect(getReviewReport).toHaveBeenCalledTimes(2)
  expect(sessionStorage.length).toBe(0)
})

it('keeps writes disabled when capability is absent', () => {
  capability.enabled = false
  mount()
  expect(screen.getByText('此部署尚未启用报告审核写入')).toBeTruthy()
  expect(screen.getByText('提交报告审核').closest('button')?.disabled).toBe(true)
  expect(getReviewReport).not.toHaveBeenCalled()
  expect(submitResultReview).not.toHaveBeenCalled()
})

it.each(['run-2', 'run-3'])('does not offer a new review when Current is %s', (currentRunId) => {
  render(<MemoryRouter><ResultReviewForm workspaceId="w" occurrenceId="o" currentRunId={currentRunId} candidateRunId="run-2" onSaved={vi.fn()} /></MemoryRouter>)
  expect(screen.queryByRole('button', { name: '审核此候选报告' })).toBeNull()
  expect(getReviewReport).not.toHaveBeenCalled()
  expect(submitResultReview).not.toHaveBeenCalled()
})
