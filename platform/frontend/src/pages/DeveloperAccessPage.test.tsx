import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { ApiProvider } from '../api/context'
import { createApiClient } from '../api/client'
import type { Workspace } from '../types'
import { DeveloperAccessPage } from './DeveloperAccessPage'

afterEach(() => cleanup())

const workspace: Workspace = {
  id: 'wsp_developer',
  name: 'desktop-client',
  display_name: 'Desktop Client',
  platform: 'windows',
  default_architecture: 'x86_64',
  retention_days: 180,
  symbol_inventory_version: 0,
  in_app_rule_version: 0,
  in_app_rules: { include_modules: [], exclude_modules: [] },
  created_at: '2026-08-25T00:00:00Z',
}

describe('DeveloperAccessPage', () => {
  it('shows fixed downloads, workspace init command, and server capability', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify([{
      producer: 'msvc',
      status: 'supported',
      artifact_format: 'windows-x64-msvc-full-pdb-7.0',
      fixture_suite: 'phase0-golden',
      gate: 'phase0',
      publication_contracts: ['1.0'],
      minimum_client_version: '1.0.0',
      build_publications_enabled: true,
    }]), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const api = createApiClient({ baseUrl: '/api/v3', fetcher })
    render(<ApiProvider api={api}><DeveloperAccessPage workspace={workspace} /></ApiProvider>)

    expect(fetcher).not.toHaveBeenCalled()
    expect(screen.getByRole('link', { name: /Windows x64/ }).getAttribute('href')).toBe('/downloads/crashcap/windows-x86_64/crashcap.exe')
    expect(screen.getByText(/upload .*--workspace desktop-client/)).toBeTruthy()
  })
})
