import { act, cleanup, fireEvent, render as renderBase, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useState, type ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { ApplicationTheme } from '../theme/ApplicationTheme'
import { Authentication, useIdentity } from './Authentication'
import { TokensPanel } from '../pages/AccountPage'
import { clearIdentity, setIdentity, type LoginIdentity } from '../api/authTransport'

const alice: LoginIdentity = { user: { id: 'alice', username: 'alice', display_name: 'Alice', kind: 'human', role: 'member', enabled: true, must_change_password: false }, csrf_token: 'alice-csrf' }
const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status })
function render(children: ReactNode) { return renderBase(<ApplicationTheme><MemoryRouter>{children}</MemoryRouter></ApplicationTheme>) }
function Draft() {
  const [text, setText] = useState('')
  return <><div>当前用户 {useIdentity()?.username}</div><input aria-label="审核草稿" value={text} onChange={e => setText(e.target.value)} /></>
}
beforeEach(() => { clearIdentity(); localStorage.clear(); sessionStorage.clear() })
afterEach(() => { cleanup(); clearIdentity(); vi.unstubAllGlobals() })

it('restores the cookie session, preserves drafts on expiry, and resumes the same account', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(alice)))
  render(<Authentication><Draft /></Authentication>)
  fireEvent.change(await screen.findByLabelText('审核草稿'), { target: { value: '尚未提交的审核' } })
  act(() => setIdentity(null))
  expect(screen.queryByRole('textbox', { name: '审核草稿' })).toBeNull()
  expect(screen.getByText('登录崩溃分析平台')).toBeTruthy()
  act(() => setIdentity({ ...alice, csrf_token: 'renewed' }))
  expect((screen.getByLabelText('审核草稿') as HTMLInputElement).value).toBe('尚未提交的审核')
  expect(localStorage.length).toBe(0)
  expect(sessionStorage.length).toBe(0)
})

it('discards the previous account’s component state when another account signs in', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(alice)))
  render(<Authentication><Draft /></Authentication>)
  fireEvent.change(await screen.findByLabelText('审核草稿'), { target: { value: 'Alice draft' } })
  act(() => setIdentity(null))
  act(() => setIdentity({ ...alice, user: { ...alice.user, id: 'bob', username: 'bob' } }))
  expect(screen.getByText('当前用户 bob')).toBeTruthy()
  expect((screen.getByLabelText('审核草稿') as HTMLInputElement).value).toBe('')
})

it('unmounts private state on explicit logout, including a later login to the same account', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(alice)))
  render(<Authentication><Draft /></Authentication>)
  fireEvent.change(await screen.findByLabelText('审核草稿'), { target: { value: 'private' } })
  act(() => clearIdentity())
  expect(screen.queryByLabelText('审核草稿')).toBeNull()
  act(() => setIdentity(alice))
  expect((screen.getByLabelText('审核草稿') as HTMLInputElement).value).toBe('')
})

it('registers without auto-login, then logs in through the form without storing credentials', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(reply({}, 401)).mockResolvedValueOnce(reply(alice.user, 201)).mockResolvedValueOnce(reply(alice))
  vi.stubGlobal('fetch', fetcher)
  render(<Authentication><Draft /></Authentication>)
  fireEvent.click(await screen.findByRole('button', { name: '注册账号' }))
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
  fireEvent.change(screen.getByLabelText('显示名'), { target: { value: 'Alice' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'a unique test password' } })
  fireEvent.click(screen.getByRole('button', { name: /注\s*册/ }))
  await screen.findByText('账号已创建，请登录')
  expect(screen.queryByLabelText('审核草稿')).toBeNull()
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'a unique test password' } })
  fireEvent.click(screen.getByRole('button', { name: /^登\s*录$/ }))
  await screen.findByText('当前用户 alice')
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/v3/auth/me', '/api/v3/auth/register', '/api/v3/auth/login'])
  expect(localStorage.length + sessionStorage.length).toBe(0)
})

it('requires temporary password replacement before mounting the application', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(reply({ ...alice, user: { ...alice.user, must_change_password: true } })).mockResolvedValueOnce(new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', fetcher)
  render(<Authentication><Draft /></Authentication>)
  await screen.findByText('首次登录设置密码')
  expect(screen.queryByLabelText('审核草稿')).toBeNull()
  fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'another test password' } })
  fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'another test password' } })
  fireEvent.click(screen.getByRole('button', { name: '修改密码并重新登录' }))
  await waitFor(() => expect(screen.getByText('密码已更新，请重新登录')).toBeTruthy())
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ current_password: '', new_password: 'another test password' })
  expect(screen.queryByLabelText('审核草稿')).toBeNull()
})

it('removes a token modal rendered through a portal when the session expires', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/api/v3/auth/me') return reply(alice)
    if (init?.method === 'POST') return reply({ token: 'ccp_TEST_SECRET_SENTINEL_0123456789' })
    return reply([])
  }))
  render(<Authentication><TokensPanel /></Authentication>)
  fireEvent.change(await screen.findByLabelText('用途'), { target: { value: 'test pipeline' } })
  fireEvent.click(screen.getByRole('button', { name: '创建令牌' }))
  await screen.findByLabelText('新令牌')
  act(() => setIdentity(null))
  await waitFor(() => expect(screen.queryByLabelText('新令牌')).toBeNull())
  await act(async () => setIdentity({ ...alice, csrf_token: 'renewed' }))
  expect(screen.queryByLabelText('新令牌')).toBeNull()
})
