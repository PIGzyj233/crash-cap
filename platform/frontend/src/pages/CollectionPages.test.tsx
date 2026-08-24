import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App as AntApp } from 'antd'
import { ApiProvider } from '../api/context'
import { createApiClient } from '../api/client'
import type { Build, CrashGroup, Workspace } from '../types'
import { BuildPage } from './BuildPage'
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

const build: Build = {
  id: 'bld_collection_pages',
  workspace_id: workspace.id,
  version: '1.0.0-test',
  build_number: null,
  commit_sha: null,
  channel: null,
  architecture: 'x86_64',
  toolchain: null,
  producer: null,
  producer_build_id: null,
  manifest_object_key: null,
  manifest_schema_version: null,
  source_bundle_config: null,
  created_at: '2026-08-24T00:00:00Z',
  modules: [],
  artifacts: [],
  groups: [],
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
  first_build_id: build.id,
  last_build_id: build.id,
  representative_stack: [],
  build_distribution: [{ build_id: build.id, version: build.version, count: 1 }],
  occurrence_ids: ['occ_collection_pages'],
}

let workspaceSequence = 0

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderBuildPage(fetcher: typeof fetch, initialBuildId?: string) {
  const testWorkspace = { ...workspace, id: `${workspace.id}_${++workspaceSequence}` }
  const api = createApiClient({ baseUrl: '/api/v1', fetcher })
  const result = render(
    <AntApp>
      <ApiProvider api={api}>
        <BuildPage workspace={testWorkspace} initialBuildId={initialBuildId} onOpenOccurrence={() => undefined} />
      </ApiProvider>
    </AntApp>,
  )
  return { ...result, workspace: testWorkspace }
}

function renderGroupPage(fetcher: typeof fetch, initialGroupId?: string) {
  const testWorkspace = { ...workspace, id: `${workspace.id}_${++workspaceSequence}` }
  const api = createApiClient({ baseUrl: '/api/v1', fetcher })
  const result = render(
    <AntApp>
      <ApiProvider api={api}>
        <GroupPage workspace={testWorkspace} initialGroupId={initialGroupId} onOpenOccurrence={() => undefined} />
      </ApiProvider>
    </AntApp>,
  )
  return { ...result, workspace: testWorkspace }
}

describe('BuildPage collection states', () => {
  it('shows a terminal empty state without requesting an undefined Build', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse([]))
    const { container, workspace: testWorkspace } = renderBuildPage(fetcher)

    expect(await screen.findByText('尚未创建 Build')).toBeTruthy()
    expect(screen.getByText('还没有 Build')).toBeTruthy()
    expect(container.querySelector('.ant-spin-spinning')).toBeNull()
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(String(fetcher.mock.calls[0][0])).toContain(`/workspaces/${testWorkspace.id}/builds?`)
  })

  it('opens the existing create modal from the empty-state action', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse([]))
    renderBuildPage(fetcher)

    fireEvent.click(await screen.findByRole('button', { name: /创建第一个 Build/ }))
    expect(within(await screen.findByRole('dialog')).getByText('创建 Build')).toBeTruthy()
  })

  it('shows a retryable list error instead of a permanent spinner', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ error: { code: 'TEST', message: 'failed' } }, 500))
    const { container } = renderBuildPage(fetcher)

    expect((await screen.findAllByText('Build 列表加载失败', undefined, { timeout: 4_000 })).length).toBe(2)
    expect(container.querySelector('.ant-spin-spinning')).toBeNull()
    const callsBeforeRetry = fetcher.mock.calls.length
    fireEvent.click(screen.getAllByRole('button', { name: /重\s*试/ })[0])
    await waitFor(() => expect(fetcher.mock.calls.length).toBeGreaterThan(callsBeforeRetry))
  })

  it('shows a retryable detail error for a selected Build', async () => {
    const testBuild = { ...build, id: 'bld_detail_error' }
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = String(input)
      if (url.includes('/workspaces/') && url.includes('/builds?')) return jsonResponse([testBuild])
      if (url.endsWith(`/builds/${testBuild.id}`)) return jsonResponse({ error: { code: 'TEST', message: 'failed' } }, 500)
      throw new Error(`Unexpected request: ${url}`)
    })
    const { container } = renderBuildPage(fetcher)

    expect(await screen.findByText('Build 详情加载失败', undefined, { timeout: 4_000 })).toBeTruthy()
    expect(container.querySelector('.ant-spin-spinning')).toBeNull()
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeTruthy()
  })

  it('keeps selecting the first Build and rendering its details', async () => {
    const testBuild = { ...build, id: 'bld_happy_path' }
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = String(input)
      if (url.includes('/workspaces/') && url.includes('/builds?')) return jsonResponse([testBuild])
      if (url.endsWith(`/builds/${testBuild.id}`)) return jsonResponse(testBuild)
      throw new Error(`Unexpected request: ${url}`)
    })
    const { container } = renderBuildPage(fetcher)

    expect(await screen.findByText('Manifest modules')).toBeTruthy()
    expect(screen.getByText('Artifact 上传')).toBeTruthy()
    expect(container.querySelector('.ant-spin-spinning')).toBeNull()
  })
})

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
    expect(screen.getByText('Build 分布')).toBeTruthy()
    expect(container.querySelector('.ant-spin-spinning')).toBeNull()
  })
})
