import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { App } from '../App'
import { ApiProvider } from '../api/context'
import { clearIdentity, currentUser, setIdentity, type LoginIdentity } from '../api/authTransport'
import { createMockApiClient } from '../api/mock'
import { Authentication } from '../components/Authentication'
import { ApplicationTheme } from '../theme/ApplicationTheme'

const admin: LoginIdentity = { user: { id: 'admin', username: 'admin', display_name: '系统管理员', role: 'admin', kind: 'human', enabled: true, must_change_password: false }, csrf_token: 'test-admin-proof' }
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
function Location() { return <output data-testid="location">{useLocation().pathname}</output> }
function show(path = '/', identity = admin, logout: () => Promise<Response> = async () => new Response(null, { status: 204 }), api = createMockApiClient()) {
  const fetcher = vi.fn().mockImplementation(async (url: string) => {
    if (url === '/api/v3/auth/me') return json(identity)
    if (url === '/api/v3/auth/logout') return logout()
    return json([])
  })
  vi.stubGlobal('fetch', fetcher)
  render(<ApplicationTheme><MemoryRouter initialEntries={[path]}><Location /><Authentication><ApiProvider api={api}><App /></ApiProvider></Authentication></MemoryRouter></ApplicationTheme>)
  return fetcher
}
beforeEach(() => { clearIdentity(); sessionStorage.clear(); localStorage.clear() })
afterEach(() => { cleanup(); clearIdentity(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it.each(['/', '/account', '/admin/users', '/w/wsp_demo/occurrences', '/missing'])('keeps a single header and visible logout on %s using the real authentication boundary', async path => {
  show(path)
  const header = await screen.findByRole('banner')
  expect(screen.getAllByRole('banner')).toHaveLength(1)
  expect(within(header).getByRole('button', { name: /退出登录/ })).toBeTruthy()
  expect(within(header).getByRole('link', { name: '上传文件' }).getAttribute('href')).toContain(path.startsWith('/w/') ? '/w/wsp_demo/upload' : '/upload')
  if (path.startsWith('/w/')) expect(within(header).getByRole('link', { name: '工作空间' }).getAttribute('aria-current')).toBe('page')
})

it.each(['admin', 'member'])('exposes account management only to %s as appropriate', async role => {
  show('/', { ...admin, user: { ...admin.user, role } })
  fireEvent.click(await screen.findByRole('button', { name: /账号菜单/ }))
  expect(await screen.findByRole('menuitem', { name: /个人账号/ })).toBeTruthy()
  expect(!!screen.queryByRole('menuitem', { name: /账号管理/ })).toBe(role === 'admin')
})

it('logs out from both account-page entry points with one request and remounts the login screen at the same URL', async () => {
  let finish!: (response: Response) => void
  const response = new Promise<Response>(resolve => { finish = resolve })
  const fetcher = show('/account', admin, () => response)
  await screen.findByRole('heading', { level: 1, name: '个人账号' })
  const buttons = screen.getAllByRole('button', { name: /退出登录/ })
  expect(buttons).toHaveLength(2)
  fireEvent.click(buttons[0]); fireEvent.click(buttons[1])
  expect(screen.getAllByRole('button', { name: /正在退出/ }).every(button => button.hasAttribute('disabled'))).toBe(true)
  expect(fetcher.mock.calls.filter(([url]) => url === '/api/v3/auth/logout')).toHaveLength(1)
  await act(async () => finish(new Response(null, { status: 204 })))
  expect(await screen.findByRole('heading', { name: '登录崩溃分析平台' })).toBeTruthy()
  expect(screen.queryByRole('banner')).toBeNull()
  expect(screen.getByTestId('location').textContent).toBe('/account')
  expect(currentUser()).toBeNull()
})

it.each([403, 500, 'network'] as const)('leaves the session intact and allows retry after %s logout failure', async failure => {
  show('/', admin, async () => { if (failure === 'network') throw new TypeError('offline'); return json({ error: { code: 'FAILED' } }, failure) })
  fireEvent.click(await screen.findByRole('button', { name: /退出登录/ }))
  expect(await screen.findByText('退出失败，请重试')).toBeTruthy()
  expect(currentUser()?.id).toBe('admin')
  await waitFor(() => expect(screen.getByRole('button', { name: /退出登录/ }).hasAttribute('disabled')).toBe(false))
})

it('treats an expired platform session as explicit logout', async () => {
  show('/', admin, async () => json({ error: { code: 'UNAUTHENTICATED' } }, 401))
  fireEvent.click(await screen.findByRole('button', { name: /退出登录/ }))
  await screen.findByRole('heading', { name: '登录崩溃分析平台' })
  expect(currentUser()).toBeNull()
})

it('allows a restricted temporary-password session to exit without opening business pages', async () => {
  const fetcher = show('/', { ...admin, user: { ...admin.user, must_change_password: true } })
  await screen.findByRole('heading', { name: '首次登录设置密码' })
  expect(screen.queryByRole('banner')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /退出登录/ }))
  await screen.findByRole('heading', { name: '登录崩溃分析平台' })
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/v3/auth/me', '/api/v3/auth/logout'])
})

it('uses a drawer at compact widths and closes it with Escape', async () => {
  const matchMedia = window.matchMedia
  vi.spyOn(window, 'matchMedia').mockImplementation(query => ({ ...matchMedia(query), matches: query === '(max-width: 1199px)' }))
  show('/w/wsp_demo/overview')
  await screen.findByRole('heading', { level: 1 })
  const button = screen.getByRole('button', { name: '打开导航' })
  button.focus()
  fireEvent.click(button)
  const drawer = await screen.findByRole('dialog')
  expect(within(drawer).getByRole('navigation', { name: '平台导航' })).toBeTruthy()
  expect(within(drawer).getByRole('navigation', { name: '工作空间任务' })).toBeTruthy()
  fireEvent.keyDown(drawer, { key: 'Escape', keyCode: 27 })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await waitFor(() => expect(document.activeElement).toBe(button))
})

it('preserves global navigation when a workspace cannot be loaded', async () => {
  const api = createMockApiClient()
  vi.spyOn(api, 'getWorkspace').mockRejectedValue(new Error('unavailable'))
  show('/w/wsp_demo/overview', admin, undefined, api)
  await screen.findByText('Workspace 加载失败', {}, { timeout: 3000 })
  expect(screen.getByRole('button', { name: /退出登录/ })).toBeTruthy()
  act(() => setIdentity(null))
  await screen.findByRole('heading', { name: '登录崩溃分析平台' })
  expect(screen.queryByRole('banner')).toBeNull()
})
