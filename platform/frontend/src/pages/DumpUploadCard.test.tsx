import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, expect, it, vi } from 'vitest'
import { DumpUploadCard } from './WorkspaceOverviewPage'
import type { Workspace } from '../types'

const mock = vi.hoisted(() => ({ enabled: true, api: {
  initSubmissionUpload: vi.fn(), initDumpUpload: vi.fn(), uploadPresigned: vi.fn(), completeUpload: vi.fn(), waitForUpload: vi.fn(),
} }))
vi.mock('../api/context', () => ({ useApi: () => mock.api }))
vi.mock('../api/hooks', () => ({
  useBuilds: () => ({ data: [] }),
  useCapabilities: () => ({ data: { enabled_writes: mock.enabled ? ['submission_labels'] : [] } }),
  useWorkspaceOverview: vi.fn(),
}))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it.each([true, false])('submits labels only through the enabled API: %s', async (enabled) => {
  mock.enabled = enabled
  mock.api.initSubmissionUpload.mockResolvedValue({ upload_id: 'upl-new' })
  mock.api.initDumpUpload.mockResolvedValue({ upload_id: 'upl-new' })
  mock.api.uploadPresigned.mockResolvedValue({})
  mock.api.completeUpload.mockResolvedValue({})
  mock.api.waitForUpload.mockResolvedValue({ verification_status: 'ACCEPTED', occurrence_id: 'occ-one' })
  const open = vi.fn()
  const { container } = render(<App><DumpUploadCard workspace={{ id: 'wsp-one' } as Workspace} onOpenOccurrence={open} /></App>)
  if (enabled) {
    fireEvent.change(screen.getByLabelText('测试版本（人工，可选）'), { target: { value: ' test-v1 ' } })
    fireEvent.change(screen.getByLabelText('测试批次（可选）'), { target: { value: ' batch-2 ' } })
    fireEvent.change(screen.getByLabelText('本次提交来源'), { target: { value: ' QA team ' } })
  } else expect(screen.queryByLabelText('测试版本（人工，可选）')).toBeNull()
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [new File(['MDMP'], 'test.dmp')] } })
  const start = screen.getByRole('button', { name: /开始上传并分析/ })
  await waitFor(() => expect(start.hasAttribute('disabled')).toBe(false))
  fireEvent.click(start)
  await waitFor(() => expect(open).toHaveBeenCalledWith('occ-one'))
  if (enabled) {
    expect(mock.api.initSubmissionUpload).toHaveBeenCalledWith('wsp-one', expect.objectContaining({ label: 'test-v1', batch: 'batch-2', source: 'QA team' }))
    expect(mock.api.initDumpUpload).not.toHaveBeenCalled()
  } else {
    expect(mock.api.initDumpUpload).toHaveBeenCalledOnce()
    expect(mock.api.initSubmissionUpload).not.toHaveBeenCalled()
  }
})
