import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App as AntApp } from 'antd'
import { ApiProvider } from '../api/context'
import { MemoryRouter } from 'react-router-dom'
import { createApiClient } from '../api/client'
import type { CrashGroup, Workspace } from '../types'
import { GroupPage } from './GroupPage'

afterEach(() => cleanup())

const workspace: Workspace = {
  id: 'wsp_collection_pages',
  name: 'collection-pages',
  display_name: 'Collection Pages',
  platform: 'windows',
  default_architecture: 'x86_64',
  retention_days: 30,
  symbol_inventory_version: 0,
  in_app_rule_version: 0,
  in_app_rules: { include_modules: [], exclude_modules: [] },
  created_at: '2026-08-24T00:00:00Z',
}

const group: CrashGroup = {
  id: 'grp_collection_pages',
  workspace_id: workspace.id,
  group_type: 'exact',
  fingerprint: 'exact-fingerprint',
  title: 'render!crash',
  status: 'open',
  owner: null,
  issue_url: null,
  first_seen: '2026-08-24T00:00:00Z',
  last_seen: '2026-08-24T00:00:00Z',
  occurrence_count: 1,
  representative_stack: [],
  version_distribution: [{ version: '1.0.0-test', count: 1 }],
  occurrence_ids: ['occ_collection_pages'],
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderGroupPage(fetcher: typeof fetch, initialGroupId?: string) {
  const testWorkspace = workspace
  const api = createApiClient({ baseUrl: '/api/v3', fetcher })
  const result = render(
    <AntApp>
      <ApiProvider api={api}>
        <MemoryRouter><GroupPage workspace={testWorkspace} initialGroupId={initialGroupId} /></MemoryRouter>
      </ApiProvider>
    </AntApp>,
  )
  return { ...result, workspace: testWorkspace }
}

describe('GroupPage collection states', () => {
  it('shows a terminal empty state for a Workspace without Exact Groups', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse([]))
    const { container } = renderGroupPage(fetcher)

    expect(await screen.findByText('暂无 Exact Group；证据不足的 Occurrence 会保留为 Unclassified')).toBeTruthy()
    expect(screen.getByText('没有 Exact Group；Unclassified 不建伪组')).toBeTruthy()
    expect(container.querySelector('.ant-spin-spinning')).toBeNull()
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('shows a retryable Exact Groups list error', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ error: { code: 'TEST', message: 'failed' } }, 500))
    const { container } = renderGroupPage(fetcher)

    expect((await screen.findAllByText('Exact Groups 加载失败', undefined, { timeout: 4_000 })).length).toBe(2)
    expect(container.querySelector('.ant-spin-spinning')).toBeNull()
    const callsBeforeRetry = fetcher.mock.calls.length
    fireEvent.click(screen.getAllByRole('button', { name: /重\s*试/ })[0])
    await waitFor(() => expect(fetcher.mock.calls.length).toBeGreaterThan(callsBeforeRetry))
  })

  it('shows a retryable Exact Group detail error', async () => {
    const testGroup = { ...group, id: 'grp_detail_error' }
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = String(input)
      if (url.includes('/workspaces/') && url.includes('/groups?')) return jsonResponse([testGroup])
      if (url.endsWith(`/groups/${testGroup.id}`)) return jsonResponse({ error: { code: 'TEST', message: 'failed' } }, 500)
      throw new Error(`Unexpected request: ${url}`)
    })
    const { container } = renderGroupPage(fetcher)

    expect(await screen.findByText('Exact Group 详情加载失败', undefined, { timeout: 4_000 })).toBeTruthy()
    expect(container.querySelector('.ant-spin-spinning')).toBeNull()
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeTruthy()
  })

  it('keeps selecting the first Exact Group and rendering its details', async () => {
    const testGroup = { ...group, id: 'grp_happy_path' }
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = String(input)
      if (url.includes('/workspaces/') && url.includes('/groups?')) return jsonResponse([testGroup])
      if (url.endsWith(`/groups/${testGroup.id}`)) return jsonResponse(testGroup)
      throw new Error(`Unexpected request: ${url}`)
    })
    const { container } = renderGroupPage(fetcher)

    expect(await screen.findByText('这个组有足够的 Exact 证据')).toBeTruthy()
    expect(screen.getByText('版本分布')).toBeTruthy()
    expect(container.querySelector('.ant-spin-spinning')).toBeNull()
  })
})
