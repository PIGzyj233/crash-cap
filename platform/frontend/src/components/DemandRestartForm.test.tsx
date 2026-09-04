import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { DemandRestartForm } from './DemandRestartForm'
import { CrashCapApiError } from '../api/client'
import type { components } from '../generated/openapi'

const { restart, capability } = vi.hoisted(() => ({ restart: vi.fn(), capability: { enabled: true } }))
vi.mock('../api/context', () => ({ useApi: () => ({ restartAnalysisDemand: restart }) }))
vi.mock('../api/hooks', () => ({ useCapabilities: () => ({ data: { enabled_writes: capability.enabled ? ['analysis_demand_restarts'] : [] } }) }))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks(); sessionStorage.clear(); capability.enabled = true })

function mount(state: components['schemas']['DemandStatusResponse']['state'] = 'retry_exhausted') {
  return render(<DemandRestartForm workspaceId="w" occurrenceId="o" demand={{ demand_id: 'd', occurrence_id: 'o', state, generation: 3, change_sequence: 8, retry_attempt: 2, run_id: null, reason: 'CORE_TIMEOUT', not_before: null }} onSaved={vi.fn()} />)
}

it('replays the exact saved request after reload and later progress', async () => {
  restart.mockRejectedValueOnce(new Error('response lost')).mockResolvedValueOnce({})
  mount()
  fireEvent.change(screen.getByLabelText('重新分析说明'), { target: { value: '服务已恢复' } })
  fireEvent.click(screen.getByText('请求重新分析'))
  await screen.findByText('response lost')
  const first = structuredClone(restart.mock.calls[0][2])
  expect(first).toMatchObject({ expected_generation: 3, expected_sequence: 8, rationale: '服务已恢复' })
  cleanup()
  capability.enabled = false
  mount('updated')
  fireEvent.click(screen.getByText('确认此前重开请求'))
  await screen.findByText('重新分析请求已受理，尚未完成分析。')
  expect(restart.mock.calls[1][2]).toEqual(first)
  expect(sessionStorage.length).toBe(0)
})

it('does not offer a fresh restart for a running demand', () => {
  mount('running')
  expect(screen.queryByText('请求重新分析')).toBeNull()
})

it('allows clearing a definitively rejected stale request without resending it', async () => {
  restart.mockRejectedValueOnce(new CrashCapApiError('页面已过期', 409, { error: { code: 'STALE_DEMAND', message: '页面已过期' } }))
  mount()
  fireEvent.change(screen.getByLabelText('重新分析说明'), { target: { value: '服务已恢复' } })
  fireEvent.click(screen.getByText('请求重新分析'))
  await screen.findByText('页面已过期')
  expect(screen.getByText('确认此前重开请求').closest('button')?.disabled).toBe(true)
  fireEvent.click(screen.getByText('清除已拒绝请求并刷新状态'))
  expect(sessionStorage.length).toBe(0)
  expect(restart).toHaveBeenCalledTimes(1)
  expect(screen.getByLabelText('重新分析说明')).not.toHaveProperty('disabled', true)
})

it('keeps a fresh request disabled without the server capability', () => {
  capability.enabled = false
  mount()
  expect(screen.getByText('请求重新分析').closest('button')?.disabled).toBe(true)
  expect(restart).not.toHaveBeenCalled()
})

it('does not send if browser storage cannot preserve the request', async () => {
  mount()
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
  fireEvent.change(screen.getByLabelText('重新分析说明'), { target: { value: '服务已恢复' } })
  fireEvent.click(screen.getByText('请求重新分析'))
  await screen.findByText('无法暂存重开请求，尚未提交。请恢复浏览器存储后重试。')
  expect(restart).not.toHaveBeenCalled()
})
