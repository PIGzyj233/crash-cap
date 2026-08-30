import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { ApiProvider } from '../api/context'
import { createApiClient } from '../api/client'
import { createMockApiClient } from '../api/mock'
import { App } from '../App'

afterEach(() => {
  cleanup()
  localStorage.clear()
})

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

function renderApp(path: string, api = createMockApiClient()) {
  return render(<ApiProvider api={api}><MemoryRouter initialEntries={[path]}><LocationProbe /><App /></MemoryRouter></ApiProvider>)
}

describe('stable Crash-Cap routes', () => {
  it('keeps / on the platform home while migrating legacy Workspace JSON to an ID shortcut', async () => {
    localStorage.setItem('crash-cap.workspace', JSON.stringify({ id: 'wsp_demo', name: 'stale-client-copy' }))
    renderApp('/')
    const heading = await screen.findByRole('heading', { level: 1, name: 'Crash-Cap' })
    await waitFor(() => expect(document.activeElement).toBe(heading))
    expect(screen.getByTestId('location').textContent).toBe('/')
    expect(localStorage.getItem('crash-cap.workspace')).toBeNull()
    expect(localStorage.getItem('crash-cap.lastWorkspaceId')).toBe('wsp_demo')
    expect(await screen.findByText('继续上次 Workspace')).toBeTruthy()
  })

  it('restores a filtered Crash Inbox URL and renders semantic report links', async () => {
    renderApp('/w/wsp_demo/occurrences?latest_status=FAILED&q=render')
    const heading = await screen.findByRole('heading', { level: 1, name: 'Crash Inbox' })
    await waitFor(() => expect(document.activeElement).toBe(heading))
    expect(screen.getByTestId('location').textContent).toContain('latest_status=FAILED')
    expect((await screen.findAllByText('FAILED')).length).toBeGreaterThan(0)
    const reportLinks = screen.getAllByRole('link')
    expect(reportLinks.some((link) => link.getAttribute('href') === '/w/wsp_demo/occurrences/occ_latest_failed')).toBe(true)
    expect(screen.getAllByText('完成').length).toBeGreaterThan(0)
    expect(screen.getAllByText('失败').length).toBeGreaterThan(0)
  })

  it('restores report tab and run from a directly opened URL', async () => {
    const api = createMockApiClient()
    await api.getOccurrence('occ_demo')
    renderApp('/w/wsp_demo/occurrences/occ_demo?tab=modules&run=run_demo', api)
    expect(await screen.findByRole('heading', { level: 1, name: /EXCEPTION_ACCESS_VIOLATION/ })).toBeTruthy()
    expect(screen.getByRole('tab', { name: 'Modules' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByTestId('location').textContent).toBe('/w/wsp_demo/occurrences/occ_demo?tab=modules&run=run_demo')
  })

  it('shows a terminal Workspace 404 and removes only the invalid last shortcut', async () => {
    localStorage.setItem('crash-cap.lastWorkspaceId', 'wsp_missing')
    const api = createApiClient({ baseUrl: '/api/v1', fetcher: async (input) => {
      const path = new URL(String(input), 'http://test').pathname
      if (path.endsWith('/artifact-producers')) return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
      return new Response(JSON.stringify({ error: { code: 'NOT_FOUND', message: 'missing', details: {} } }), { status: 404, headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'req_missing_workspace' } })
    } })
    renderApp('/w/wsp_missing/overview', api)
    expect(await screen.findByText('Workspace 不存在')).toBeTruthy()
    expect(screen.queryByRole('link', { name: '返回 Workspace' })).toBeNull()
    expect(localStorage.getItem('crash-cap.lastWorkspaceId')).toBeNull()
  })
})
