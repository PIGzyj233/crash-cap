import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { App as AntApp } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import { ApiProvider } from '../api/context'
import { createApiClient } from '../api/client'
import type { SymbolHealthRow, Workspace } from '../types'
import { SymbolHealthPage } from './SymbolHealthPage'

afterEach(() => cleanup())

const workspace: Workspace = {
  id: 'wsp_symbol_navigation',
  name: 'symbol-navigation',
  display_name: 'Symbol Navigation',
  platform: 'windows',
  default_architecture: 'x86_64',
  retention_days: 30,
  symbol_inventory_version: 0,
  in_app_rule_version: 0,
  in_app_rules: { include_modules: [], exclude_modules: [] },
  created_at: '2026-08-30T00:00:00Z',
}

const inventory: SymbolHealthRow = {
  build_id: 'bld_pdb_only',
  module_id: 'mod_pdb_only',
  code_file: 'target.exe',
  debug_file: 'target.pdb',
  code_id: null,
  debug_id: 'cf34e342f3604e87ba508387bb89876630',
  status: 'missing',
  affected_occurrence_count: 0,
  first_seen: '2026-08-30T00:00:00Z',
  last_seen: '2026-08-30T00:00:00Z',
  occurrence_ids: [],
}

it('links an affected canonical identity even when it cannot be assigned to a Build module', async () => {
  const affected: SymbolHealthRow = {
    ...inventory,
    build_id: null,
    module_id: null,
    code_file: 'C:\\fixtures\\golden_target_debug.exe',
    debug_file: 'C:\\fixtures\\golden_target_debug.pdb',
    code_id: '6A871E18CA000',
    affected_occurrence_count: 1,
    occurrence_ids: ['occ_symbol_navigation'],
  }
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    const url = String(input)
    const body = url.endsWith('/symbols/health') ? [inventory] : url.endsWith('/symbols/missing') ? [affected] : null
    if (!body) throw new Error(`Unexpected request: ${url}`)
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  const api = createApiClient({ baseUrl: '/api/v1', fetcher })
  render(
    <AntApp>
      <ApiProvider api={api}>
        <MemoryRouter><SymbolHealthPage workspace={workspace} /></MemoryRouter>
      </ApiProvider>
    </AntApp>,
  )

  const link = await screen.findByRole('link', { name: /occ_symbol_navigation/ })
  expect(link.getAttribute('href')).toBe(`/w/${workspace.id}/occurrences/occ_symbol_navigation`)
  expect(screen.getByRole('button', { name: '批量 Reprocess (1)' }).classList.contains('ant-btn-loading')).toBe(false)
  expect(fetcher).toHaveBeenCalledTimes(2)
})
