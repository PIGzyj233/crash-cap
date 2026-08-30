import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App as AntApp } from 'antd'
import { ApiProvider } from '../api/context'
import { MemoryRouter } from 'react-router-dom'
import { createApiClient } from '../api/client'
import type { Build, BuildPublicationStatus, CrashGroup, OccurrenceListItem, Workspace } from '../types'
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
  identity_mode: 'legacy',
  fingerprint_version: null,
  content_fingerprint: null,
  sealed_at: null,
  created_at: '2026-08-24T00:00:00Z',
  modules: [],
  artifacts: [],
  groups: [],
}

const resolvedOccurrence: OccurrenceListItem = {
  id: 'occ_build_navigation',
  workspace_id: workspace.id,
  occurred_at: '2026-08-24T00:00:00Z',
  uploaded_at: '2026-08-24T00:00:01Z',
  time_source: 'dump',
  current_analysis: {
    id: 'run_build_navigation',
    status: 'PARTIAL',
    resolution_method: 'reported',
    resolved_build_id: build.id,
    quality_score: 0.55,
    started_at: '2026-08-24T00:00:02Z',
    finished_at: '2026-08-24T00:00:03Z',
    duration_ms: 1000,
    error_code: null,
    error_detail: null,
  },
  latest_attempt: null,
  summary: {
    crash_type: 'crash',
    exception_code: '0xC0000005',
    exception_name: 'EXCEPTION_ACCESS_VIOLATION',
    access_type: 'read',
    fault_module: 'app.exe',
    top_function: 'crashcap::trigger_null_read',
    version: build.version,
  },
  group: null,
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

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderBuildPage(fetcher: typeof fetch, initialBuildId?: string) {
  const testWorkspace = workspace
  const api = createApiClient({ baseUrl: '/api/v1', fetcher })
  const result = render(
    <AntApp>
      <ApiProvider api={api}>
        <MemoryRouter><BuildPage workspace={testWorkspace} initialBuildId={initialBuildId} /></MemoryRouter>
      </ApiProvider>
    </AntApp>,
  )
  return { ...result, workspace: testWorkspace }
}

function renderGroupPage(fetcher: typeof fetch, initialGroupId?: string) {
  const testWorkspace = workspace
  const api = createApiClient({ baseUrl: '/api/v1', fetcher })
  const result = render(
    <AntApp>
      <ApiProvider api={api}>
        <MemoryRouter><GroupPage workspace={testWorkspace} initialGroupId={initialGroupId} /></MemoryRouter>
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
      if (url.includes('/occurrences?')) return jsonResponse({ items: [], next_cursor: null })
      throw new Error(`Unexpected request: ${url}`)
    })
    const { container } = renderBuildPage(fetcher)

    expect(await screen.findByText('Manifest modules')).toBeTruthy()
    expect(screen.getByText('Artifact 上传')).toBeTruthy()
    expect(container.querySelector('.ant-spin-spinning')).toBeNull()
  })

  it('renders semantic Occurrence links resolved to the selected Build', async () => {
    const testBuild = { ...build, id: 'bld_occurrence_navigation' }
    const occurrence = {
      ...resolvedOccurrence,
      current_analysis: { ...resolvedOccurrence.current_analysis!, resolved_build_id: testBuild.id },
    }
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = String(input)
      if (url.includes('/workspaces/') && url.includes('/builds?')) return jsonResponse([testBuild])
      if (url.endsWith(`/builds/${testBuild.id}`)) return jsonResponse(testBuild)
      if (url.includes('/occurrences?')) return jsonResponse({ items: [occurrence], next_cursor: null })
      throw new Error(`Unexpected request: ${url}`)
    })
    renderBuildPage(fetcher)

    const link = await screen.findByRole('link', { name: /EXCEPTION_ACCESS_VIOLATION/ })
    expect(link.getAttribute('href')).toBe(`/w/${workspace.id}/occurrences/${occurrence.id}`)
    expect(fetcher.mock.calls.some(([input]) => String(input).includes(`build_id=${testBuild.id}`))).toBe(true)
  })

  it('renders content identity, dirty Publication evidence, and expectation-only recovery', async () => {
    const module = { id: 'mod_content', code_file: 'app.exe', debug_file: 'app.pdb', role: 'entrypoint' as const, code_id: null, debug_id: null, in_app: true, artifact_count: 0, missing_occurrence_count: 0 }
    const testBuild: Build = {
      ...build,
      id: 'bld_content',
      producer: 'msvc',
      manifest_schema_version: '1.0',
      manifest_object_key: 'raw-builds/content/manifest.json',
      identity_mode: 'content_v1',
      fingerprint_version: 'build-content-v1',
      content_fingerprint: 'a'.repeat(64),
      modules: [module],
    }
    const expectations = [
      { module_id: module.id, module_code_file: module.code_file, kind: 'pe' as const, logical_name: module.code_file, size: 100, sha256: 'b'.repeat(64), status: 'missing' as const, artifact_id: null, artifact_blob_id: null, delivery: null, upload_id: null, rejection_reason: null },
      { module_id: module.id, module_code_file: module.code_file, kind: 'pdb' as const, logical_name: module.debug_file, size: 200, sha256: 'c'.repeat(64), status: 'rejected' as const, artifact_id: null, artifact_blob_id: null, delivery: null, upload_id: 'upl_bad', rejection_reason: 'expected_sha256_mismatch' },
    ]
    const status: BuildPublicationStatus = {
      publication: { id: 'pub_content', workspace_id: workspace.id, build_id: testBuild.id, origin: 'local', client_publication_id: 'local:test', client_version: 'crashcap/1.0.0', git_revision: 'd'.repeat(40), git_worktree_state: 'dirty', created_at: '2026-08-25T00:00:00Z', last_seen_at: '2026-08-25T00:00:00Z' },
      publications: [],
      build_id: testBuild.id,
      identity_mode: 'content_v1',
      fingerprint_version: 'build-content-v1',
      content_fingerprint: testBuild.content_fingerprint!,
      status: 'rejected',
      sealed_at: null,
      expected_artifacts: expectations,
      missing_artifacts: expectations,
      rejected_artifacts: [expectations[1]],
      ready: false,
    }
    status.publications = [status.publication!]
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = String(input)
      if (url.includes('/workspaces/') && url.includes('/builds?')) return jsonResponse([testBuild])
      if (url.endsWith(`/builds/${testBuild.id}`)) return jsonResponse(testBuild)
      if (url.endsWith(`/builds/${testBuild.id}/publication-status`)) return jsonResponse(status)
      if (url.includes('/occurrences?')) return jsonResponse({ items: [], next_cursor: null })
      throw new Error(`Unexpected request: ${url}`)
    })
    renderBuildPage(fetcher)

    expect(await screen.findByText('Dirty working tree')).toBeTruthy()
    expect(screen.getByText('Publication 托管')).toBeTruthy()
    expect(screen.getByText('LOCAL · Git dirty · dddddddddddd')).toBeTruthy()
    expect(screen.getByText('expected_sha256_mismatch')).toBeTruthy()
    expect(screen.getByText('仅用于补交缺失文件')).toBeTruthy()
    expect(screen.queryByText('Source bundle ZIP')).toBeNull()
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
