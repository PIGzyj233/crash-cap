import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { App as AntApp } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import { ApiProvider } from '../api/context'
import { createMockApiClient } from '../api/mock'
import { SymbolHealthPage } from './SymbolHealthPage'

afterEach(() => { cleanup(); sessionStorage.clear() })

it('uses one Current-impact query and links the exact issue and affected records', async () => {
  const api = createMockApiClient()
  const workspace = (await api.listWorkspaces())[0]
  const query = vi.spyOn(api, 'getSymbolIssues').mockResolvedValue({ items: [{
    id: 'issue_target', code_file: 'target.exe', debug_file: 'target.pdb', code_id: '123', debug_id: 'abc',
    reasons: { pdb_mismatch: 1 }, affected_occurrence_count: 1,
    first_seen: '2026-09-06T00:00:00Z', last_seen: '2026-09-06T00:00:00Z',
  }], total: 1, affected_occurrence_count: 1, analyzed_occurrence_count: 1, next_cursor: null })
  const legacy = vi.spyOn(api, 'getSymbolHealth')
  render(<AntApp><ApiProvider api={api}><MemoryRouter><SymbolHealthPage workspace={workspace} /></MemoryRouter></ApiProvider></AntApp>)
  expect((await screen.findByRole('link', { name: /target.exe/ })).getAttribute('href')).toBe(`/w/${workspace.id}/symbols/issue_target`)
  expect(screen.getByRole('link', { name: '1 份' }).getAttribute('href')).toBe(`/w/${workspace.id}/occurrences?symbol_issue_id=issue_target`)
  expect(screen.getByText('PDB 身份不匹配 · 1')).toBeTruthy()
  expect(screen.queryByText('Matched')).toBeNull()
  expect(query).toHaveBeenCalledTimes(1)
  expect(legacy).not.toHaveBeenCalled()
})
