import { describe, expect, it } from 'vitest'
import { createMockApiClient, parseMockScenario } from './mock'

describe('local fixture API', () => {
  it('accepts only the bounded browser visual-QA scenarios', () => {
    expect(parseMockScenario('latest-failed')).toBe('latest-failed')
    expect(parseMockScenario('not-a-scenario')).toBeUndefined()
    expect(parseMockScenario(null)).toBeUndefined()
  })

  it('supports a polling transition without a RustFS dependency', async () => {
    const api = createMockApiClient()
    const workspaces = await api.listWorkspaces()
    expect(workspaces[0].id).toBe('wsp_demo')
    const first = await api.getOccurrence('occ_demo')
    expect(first.latest_attempt?.status).toBe('ANALYZING')
    const second = await api.getOccurrence('occ_demo')
    expect(second.current_analysis?.status).toBe('COMPLETE')
    const report = await api.getOccurrenceAnalysis('occ_demo')
    const crashThread = report.threads.find((thread) => thread.is_crashing)
    expect(crashThread?.id).toBe(7)
    expect(crashThread).not.toHaveProperty('thread_id')
    expect(report.modules[0]).toHaveProperty('status', 'matched')
    expect(report.modules[0]).not.toHaveProperty('match_status')
    expect(report.threads[0].frames[0]).toMatchObject({ file: 'src/render.cpp', line: 120, module_debug_id: expect.any(String) })
    expect(report.threads[0].frames[0]).not.toHaveProperty('source_file')
    const progress: number[] = []
    const completion = await api.uploadPresigned({ upload_id: 'upl_test', method: 'PUT', url: 'http://rustfs.local/test', headers: {}, expires_in: 900 }, new File(['dmp'], 'test.dmp'), (value) => progress.push(value))
    expect(progress).toEqual([100])
    const init = await api.initUpload({ workspace_id: 'wsp_demo', file_kind: 'dmp', filename: 'test.dmp', size: 3, sha256: 'a'.repeat(64), source: 'browser' })
    const completed = await api.completeUpload(init.upload_id, completion)
    expect(completed.status).toBe('VERIFYING')
    const verified = await api.waitForUpload(init.upload_id, { intervalMs: 0, maxAttempts: 3 })
    expect(verified).toMatchObject({ status: 'ACCEPTED', verification_status: 'ACCEPTED', occurrence_id: 'occ_demo' })
  })

  it('covers empty platform, empty Inbox, processing, and Current/latest divergence', async () => {
    expect(await createMockApiClient({ scenario: 'empty-platform' }).listWorkspaces()).toEqual([])
    expect((await createMockApiClient({ scenario: 'empty-platform' }).getPlatformOverview()).workspace_count).toBe(0)
    expect((await createMockApiClient({ scenario: 'empty-occurrences' }).listOccurrences('wsp_demo')).items).toEqual([])
    const processing = (await createMockApiClient({ scenario: 'processing' }).listOccurrences('wsp_demo')).items[0]
    expect(processing.current_analysis).toBeNull()
    expect(processing.latest_attempt?.status).toBe('ANALYZING')
    const failed = (await createMockApiClient({ scenario: 'latest-failed' }).listOccurrences('wsp_demo')).items[0]
    expect(failed.current_analysis?.status).toBe('COMPLETE')
    expect(failed.latest_attempt?.status).toBe('FAILED')
  })
})
