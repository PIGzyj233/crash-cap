import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App as AntApp } from 'antd'
import { createApiClient } from '../api/client'
import { createMockApiClient } from '../api/mock'
import { ApiProvider } from '../api/context'
import type { CanonicalReport, OccurrenceDetail, ReprocessResponse, Workspace } from '../types'
import { OccurrenceReport } from './OccurrenceReport'
import { MemoryRouter } from 'react-router-dom'

afterEach(() => cleanup())

const workspace: Workspace = {
  id: 'wsp_failed_report',
  name: 'failed-report',
  display_name: 'Failed Report',
  platform: 'windows',
  default_architecture: 'x86_64',
  retention_days: 30,
  symbol_inventory_version: 1,
  in_app_rule_version: 0,
  in_app_rules: { include_modules: [], exclude_modules: [] },
  created_at: '2026-08-26T00:00:00Z',
}

const failedOccurrence: OccurrenceDetail = {
  id: 'occ_failed_report',
  workspace_id: workspace.id,
  blob: {
    id: 'blob_failed_report',
    sha256: 'a'.repeat(64),
    size: 1024,
    dump_kind: 'user_minidump',
    verification_status: 'accepted',
    uploaded_at: '2026-08-26T00:00:00Z',
    expires_at: null,
    deleted_at: null,
  },
  reported_build_id: null,
  dump_timestamp: null,
  reported_at: null,
  occurred_at: '2026-08-26T00:00:00Z',
  uploaded_at: '2026-08-26T00:00:00Z',
  time_source: 'uploaded',
  current_analysis: null,
  latest_attempt: {
    id: 'run_failed_report',
    status: 'TIMEOUT',
    resolution_method: 'unresolved',
    resolved_build_id: null,
    quality_score: null,
    started_at: '2026-08-26T00:00:01Z',
    finished_at: '2026-08-26T00:10:01Z',
    duration_ms: 600_000,
    error_code: 'CORE_STAGE_TIMEOUT',
    error_detail: 'Core input staging exceeded its deadline',
  },
  group: null,
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('OccurrenceReport failed analysis', () => {
  it('shows only the demand restart entry for an exhausted automatic analysis', async () => {
    const api = createMockApiClient()
    vi.spyOn(api, 'getOccurrence').mockResolvedValue(failedOccurrence)
    vi.spyOn(api, 'getAnalysisDemand').mockResolvedValue({
      demand_id: 'demand_exhausted', occurrence_id: failedOccurrence.id, state: 'retry_exhausted',
      generation: 1, change_sequence: 2, retry_attempt: 1,
      run_id: failedOccurrence.latest_attempt!.id, reason: 'CORE_EXECUTION_TIMEOUT', not_before: null,
    })
    vi.spyOn(api, 'getCapabilities').mockResolvedValue({
      reader_versions: ['1.0', '1.1'], enabled_writes: ['analysis_demand_restarts'], pause_reason: null,
    })
    const reprocess = vi.spyOn(api, 'reprocessOccurrence')
    render(<AntApp><ApiProvider api={api}><MemoryRouter><OccurrenceReport workspace={workspace} occurrenceId={failedOccurrence.id} onBack={() => undefined} onOpenGroup={() => undefined} /></MemoryRouter></ApiProvider></AntApp>)
    expect(await screen.findByRole('button', { name: '请求重新分析' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'reload 重新分析' })).toBeNull()
    expect(reprocess).not.toHaveBeenCalled()
  })

  it('shows a queued update while keeping the current report available', async () => {
    const api = createMockApiClient()
    const selectedWorkspace = (await api.listWorkspaces())[0]
    await api.getOccurrence('occ_demo')
    await api.getOccurrence('occ_demo')
    vi.spyOn(api, 'getAnalysisDemand').mockResolvedValue({
      demand_id: 'demand_queued', occurrence_id: 'occ_demo', state: 'queued',
      generation: 2, change_sequence: 2, retry_attempt: 0, run_id: 'run_next', reason: null, not_before: null,
    })
    const reprocess = vi.spyOn(api, 'reprocessOccurrence')
    render(<AntApp><ApiProvider api={api}><MemoryRouter><OccurrenceReport workspace={selectedWorkspace} occurrenceId="occ_demo" onBack={() => undefined} onOpenGroup={() => undefined} /></MemoryRouter></ApiProvider></AntApp>)
    expect(await screen.findByText('已排队')).toBeTruthy()
    expect(await screen.findByRole('button', { name: /Reprocess/ })).toBeTruthy()
    expect(reprocess).not.toHaveBeenCalled()
  })

  it('declares an exact role for an unknown module without rewriting the displayed run', async () => {
    const api = createMockApiClient()
    const selectedWorkspace = (await api.listWorkspaces())[0]
    await api.getOccurrence('occ_demo')
    await api.getOccurrence('occ_demo')
    const base = await api.getOccurrenceAnalysis('occ_demo')
    if (base.schema_version !== '1.0') throw new Error('mock fixture must remain Canonical 1.0')
    const report: CanonicalReport = {
      ...base,
      modules: [
        ...base.modules,
        {
          code_file: 'plugin.dll',
          debug_file: 'plugin.pdb',
          code_id: '67A1B925A1000',
          debug_id: '94e72158e9a3443c787b78a8a3448d0d730',
          image_base: '0x190000000',
          image_size: 4096,
          role: 'unknown',
          in_app: false,
          artifact_ids: [],
          status: 'matched',
        },
      ],
    }
    vi.spyOn(api, 'getOccurrenceAnalysis').mockResolvedValue(report)
    vi.spyOn(api, 'getOccurrenceModules').mockResolvedValue(report.modules)
    vi.spyOn(api, 'getCapabilities').mockResolvedValue({
      reader_versions: ['1.0', '1.1'],
      enabled_writes: ['workspace_module_roles'],
      pause_reason: null,
    })
    const declare = vi.spyOn(api, 'declareModuleRole').mockResolvedValue({
      workspace_id: selectedWorkspace.id,
      version: 1,
      identity: {
        code_id: '67a1b925a1000',
        debug_id: '94e72158e9a3443c787b78a8a3448d0d730',
        architecture: 'x86_64',
      },
      role: 'owned',
      changed: true,
      fanout_attempt_id: 'wra_test',
    })
    render(<AntApp><ApiProvider api={api}><MemoryRouter initialEntries={['/?tab=modules']}><OccurrenceReport workspace={selectedWorkspace} occurrenceId="occ_demo" onBack={() => undefined} onOpenGroup={() => undefined} /></MemoryRouter></ApiProvider></AntApp>)
    const button = await screen.findByRole('button', { name: '声明 plugin.dll 为 owned' })
    await waitFor(() => expect(button.hasAttribute('disabled')).toBe(false))
    fireEvent.click(button)
    await waitFor(() => expect(declare).toHaveBeenCalledWith(selectedWorkspace.id, {
      identity: {
        code_id: '67A1B925A1000',
        debug_id: '94e72158e9a3443c787b78a8a3448d0d730',
        architecture: 'x86_64',
      },
      role: 'owned',
    }))
    expect(await screen.findByText(/当前历史报告保持不变/)).toBeTruthy()
    expect(screen.getByText('unknown')).toBeTruthy()
  })

  it('keeps role declaration visible but disabled when the server capability is off', async () => {
    const api = createMockApiClient({ scenario: 'role-declaration' })
    const selectedWorkspace = (await api.listWorkspaces())[0]
    await api.getOccurrence('occ_demo')
    await api.getOccurrence('occ_demo')
    vi.spyOn(api, 'getCapabilities').mockResolvedValue({
      reader_versions: ['1.0', '1.1'],
      enabled_writes: [],
      pause_reason: 'qualification_pending',
    })
    const declare = vi.spyOn(api, 'declareModuleRole')
    render(<AntApp><ApiProvider api={api}><MemoryRouter initialEntries={['/?tab=modules']}><OccurrenceReport workspace={selectedWorkspace} occurrenceId="occ_demo" onBack={() => undefined} onOpenGroup={() => undefined} /></MemoryRouter></ApiProvider></AntApp>)
    expect(await screen.findByText('精确模块角色声明当前未启用')).toBeTruthy()
    const button = await screen.findByRole('button', { name: '声明 plugin.dll 为 owned' })
    expect(button.hasAttribute('disabled')).toBe(true)
    fireEvent.click(button)
    expect(declare).not.toHaveBeenCalled()
  })

  it('renders a 1.1 report while its new write path is disabled', async () => {
    const api = createMockApiClient()
    const selectedWorkspace = (await api.listWorkspaces())[0]
    await api.getOccurrence('occ_demo')
    await api.getOccurrence('occ_demo')
    const base = await api.getOccurrenceAnalysis('occ_demo')
    const report: CanonicalReport = {
      ...base,
      schema_version: '1.1',
      symbol_resolution: { selection_version: 'pair-selection-v1', resolution_evidence_fingerprint: 'a'.repeat(64), manifest: { object_key: 'fixture/manifest', sha256: 'b'.repeat(64) }, inspect_sha256: 'c'.repeat(64), context_sha256: 'd'.repeat(64) },
      threads: base.threads.map((thread) => ({ ...thread, frames: thread.frames.map((frame, index) => ({ ...frame, module_index: null, physical_frame_index: index, unwind_method: 'unknown' as const })) })),
      modules: base.modules.map((module, index) => ({ ...module, module_index: index, source_outcomes: [], selection: { module_index: index, identity: { code_id: null, debug_id: null, architecture: 'x86_64' as const }, state: 'indeterminate' as const, candidates_complete: false, candidate_pair_ids: [], unavailable_pair_ids: [], selected_pair_id: null, reason: 'incomplete_identity' as const, candidate_evidence: { object_key: 'fixture/candidates', sha256: 'e'.repeat(64) }, review_refs: [] } })),
    }
    vi.spyOn(api, 'getOccurrenceAnalysis').mockResolvedValue(report)
    const reprocess = vi.spyOn(api, 'reprocessOccurrence')
    render(<AntApp><ApiProvider api={api}><MemoryRouter><OccurrenceReport workspace={selectedWorkspace} occurrenceId="occ_demo" onBack={() => undefined} onOpenGroup={() => undefined} /></MemoryRouter></ApiProvider></AntApp>)
    const button = await screen.findByRole('button', { name: /Reprocess/ })
    expect(button.hasAttribute('disabled')).toBe(true)
    fireEvent.click(button)
    expect(reprocess).not.toHaveBeenCalled()
  })

  it('shows failure evidence and retries without requiring a Build ID', async () => {
    const retry: ReprocessResponse = {
      ...failedOccurrence.latest_attempt!,
      id: 'run_retry',
      status: 'UPLOADED',
      started_at: null,
      finished_at: null,
      duration_ms: null,
      error_code: null,
      error_detail: null,
      created: true,
    }
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/analysis-demand')) return jsonResponse(null)
      if (url.endsWith(`/occurrences/${failedOccurrence.id}`) && !init?.method) {
        return jsonResponse(failedOccurrence)
      }
      if (url.endsWith(`/occurrences/${failedOccurrence.id}/reprocess`)) {
        return jsonResponse(retry, 202)
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const api = createApiClient({ baseUrl: '/api/v1', fetcher })

    render(
      <AntApp>
        <ApiProvider api={api}>
          <MemoryRouter initialEntries={[`/w/${workspace.id}/occurrences/${failedOccurrence.id}`]}><OccurrenceReport
            workspace={workspace}
            occurrenceId={failedOccurrence.id}
            onBack={() => undefined}
            onOpenGroup={() => undefined}
          /></MemoryRouter>
        </ApiProvider>
      </AntApp>,
    )

    expect(await screen.findByText('分析输入准备失败')).toBeTruthy()
    expect(screen.getByText('Core input staging exceeded its deadline')).toBeTruthy()
    expect(screen.getByText(/不需要预先填写 Build ID/)).toBeTruthy()
    expect(fetcher.mock.calls.some(([input]) => /\/analysis(?:\?|$)/.test(String(input)))).toBe(false)

    const retryButton = screen.getByRole('button', { name: /重新分析/ }) as HTMLButtonElement
    await waitFor(() => expect(retryButton.disabled).toBe(false))
    fireEvent.click(retryButton)
    await waitFor(() => {
      const retryCall = fetcher.mock.calls.find(([input]) =>
        String(input).endsWith(`/occurrences/${failedOccurrence.id}/reprocess`),
      )
      expect(retryCall).toBeTruthy()
      expect(JSON.parse(String(retryCall?.[1]?.body))).toEqual({ force: true })
    })
  })
})
