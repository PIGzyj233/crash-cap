import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App as AntApp } from 'antd'
import { createApiClient } from '../api/client'
import { ApiProvider } from '../api/context'
import type { OccurrenceDetail, ReprocessResponse, Workspace } from '../types'
import { OccurrenceReport } from './OccurrenceReport'

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
          <OccurrenceReport
            workspace={workspace}
            occurrenceId={failedOccurrence.id}
            onBack={() => undefined}
            onOpenGroup={() => undefined}
          />
        </ApiProvider>
      </AntApp>,
    )

    expect(await screen.findByText('分析输入准备失败')).toBeTruthy()
    expect(screen.getByText('Core input staging exceeded its deadline')).toBeTruthy()
    expect(screen.getByText(/不需要预先填写 Build ID/)).toBeTruthy()
    expect(fetcher.mock.calls.some(([input]) => String(input).includes('/analysis'))).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: /重新分析/ }))
    await waitFor(() => {
      const retryCall = fetcher.mock.calls.find(([input]) =>
        String(input).endsWith(`/occurrences/${failedOccurrence.id}/reprocess`),
      )
      expect(retryCall).toBeTruthy()
      expect(JSON.parse(String(retryCall?.[1]?.body))).toEqual({ force: true })
    })
  })
})
