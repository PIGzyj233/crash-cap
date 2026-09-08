import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AuthRequestError, authRequest, captureAccount, clearIdentity, currentUser, enableAuthentication, getLogoutPending, logoutCurrentSession, sessionFetch, setIdentity, watchSessionChanges, type LoginIdentity } from './authTransport'

const alice: LoginIdentity = { user: { id: 'alice', username: 'alice', display_name: 'Alice', kind: 'human', role: 'member', enabled: true, must_change_password: false }, csrf_token: 'alice-first' }
const bob: LoginIdentity = { user: { ...alice.user, id: 'bob', username: 'bob' }, csrf_token: 'bob-first' }
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
const ok = () => new Response('{}', { status: 200 })
const expired = () => new Response('{}', { status: 401 })
const csrf = (init: RequestInit) => new Headers(init.headers).get('X-CSRF-Token')
beforeEach(() => { enableAuthentication(); clearIdentity(); setIdentity(alice) })
afterEach(() => { clearIdentity(); vi.unstubAllGlobals() })

it('pauses concurrent expired writes and resumes both with the same user’s new CSRF proof', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(expired()).mockResolvedValueOnce(expired()).mockImplementation(async () => ok())
  const first = sessionFetch(fetcher, '/api/v3/uploads:init', { method: 'POST' })
  const second = sessionFetch(fetcher, '/api/v3/uploads/id:complete', { method: 'POST' })
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
  setIdentity({ ...alice, csrf_token: 'alice-renewed' })
  expect((await Promise.all([first, second])).map(r => r.status)).toEqual([200, 200])
  expect(fetcher.mock.calls.map(([, init]) => csrf(init!))).toEqual(['alice-first', 'alice-first', 'alice-renewed', 'alice-renewed'])
})

it('rejects an old account’s successful response after switching accounts', async () => {
  const reply = deferred<Response>()
  const fetcher = vi.fn<typeof fetch>().mockReturnValue(reply.promise)
  const request = sessionFetch(fetcher, '/api/v3/workspaces')
  const result = expect(request).rejects.toThrow('账号已切换')
  setIdentity(bob)
  reply.resolve(ok())
  await result
})

it('does not clear the new account when an old account’s 401 arrives late', async () => {
  const reply = deferred<Response>()
  const request = sessionFetch(vi.fn<typeof fetch>().mockReturnValue(reply.promise), '/api/v3/workspaces')
  const result = expect(request).rejects.toThrow('账号已切换')
  setIdentity(bob)
  reply.resolve(expired())
  await result
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(ok())
  await sessionFetch(fetcher, '/api/v3/workspaces', { method: 'POST' })
  expect(csrf(fetcher.mock.calls[0][1]!)).toBe('bob-first')
})

it('does not clear a renewed login when an earlier account request expires', async () => {
  const reply = deferred<Response>()
  vi.stubGlobal('fetch', vi.fn().mockReturnValue(reply.promise))
  const request = authRequest('/me/tokens')
  const result = expect(request).rejects.toThrow()
  setIdentity({ ...alice, csrf_token: 'alice-renewed' })
  reply.resolve(expired())
  await result
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(ok())
  const next = sessionFetch(fetcher, '/api/v3/workspaces', { method: 'POST' })
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect(csrf(fetcher.mock.calls[0][1]!)).toBe('alice-renewed')
  await next
})

it('cancels an aborted request while login is pending and never replays it', async () => {
  const controller = new AbortController()
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(expired())
  const request = sessionFetch(fetcher, '/api/v3/workspaces', { signal: controller.signal })
  const result = expect(request).rejects.toMatchObject({ name: 'AbortError' })
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
  controller.abort()
  await result
  setIdentity({ ...alice, csrf_token: 'alice-renewed' })
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('invalidates in-flight operations on explicit logout even if the same account logs back in', async () => {
  const reply = deferred<Response>()
  const request = sessionFetch(vi.fn<typeof fetch>().mockReturnValue(reply.promise), '/api/v3/workspaces')
  const result = expect(request).rejects.toThrow('账号已切换')
  clearIdentity()
  setIdentity(alice)
  reply.resolve(ok())
  await result
})

it('synchronizes account changes across tabs using only non-secret identity notifications', async () => {
  const { watchSessionChanges, currentUser } = await import('./authTransport')
  let receiver: { onmessage: ((event: MessageEvent) => void) | null } | undefined
  const post = vi.fn()
  const close = vi.fn()
  vi.stubGlobal('BroadcastChannel', class {
    onmessage: ((event: MessageEvent) => void) | null = null
    postMessage = post
    close = close
    constructor() { receiver = this }
  })
  const stop = watchSessionChanges()
  try {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(bob))))
    receiver!.onmessage!(new MessageEvent('message', { data: { type: 'login', userId: 'bob' } }))
    await vi.waitFor(() => expect(currentUser()?.id).toBe('bob'))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(bob))))
    await authRequest('/auth/login', { method: 'POST' })
    expect(post).toHaveBeenCalledWith({ type: 'login', userId: 'bob' })
    expect(JSON.stringify(post.mock.calls)).not.toContain(bob.csrf_token)
    receiver!.onmessage!(new MessageEvent('message', { data: { type: 'logout' } }))
    expect(currentUser()).toBeNull()
  } finally { stop() }
  expect(close).toHaveBeenCalledOnce()
})

it('shares one logout request, sends CSRF and invalidates the old account lifetime', async () => {
  const response = deferred<Response>()
  const fetcher = vi.fn().mockReturnValue(response.promise)
  vi.stubGlobal('fetch', fetcher)
  const check = captureAccount()
  const first = logoutCurrentSession()
  const second = logoutCurrentSession()
  expect(first).toBe(second)
  expect(getLogoutPending()).toBe(true)
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect(fetcher.mock.calls[0][0]).toBe('/api/v3/auth/logout')
  expect(fetcher.mock.calls[0][1]).toMatchObject({ method: 'POST', credentials: 'same-origin' })
  expect(csrf(fetcher.mock.calls[0][1])).toBe('alice-first')
  response.resolve(new Response(null, { status: 204 }))
  await first
  expect(currentUser()).toBeNull()
  expect(getLogoutPending()).toBe(false)
  expect(check).toThrow('账号已切换或退出')
})

it.each([403, 500, 401])('preserves the identity and structured error on an unconfirmed %i response', async status => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'UNEXPECTED', message: 'failure' } }), { status })))
  await expect(logoutCurrentSession()).rejects.toMatchObject({ status, code: 'UNEXPECTED' })
  expect(currentUser()?.id).toBe('alice')
  expect(getLogoutPending()).toBe(false)
})

it('cleans up and broadcasts exactly once when the platform session is already expired', async () => {
  const post = vi.fn()
  vi.stubGlobal('BroadcastChannel', class { onmessage = null; postMessage = post; close() {} })
  const stop = watchSessionChanges()
  try {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'UNAUTHENTICATED' } }), { status: 401 })))
    await logoutCurrentSession()
    expect(currentUser()).toBeNull()
    expect(post).toHaveBeenCalledExactlyOnceWith({ type: 'logout' })
  } finally { stop() }
})

it('does not broadcast or clear a later login when logout completes late', async () => {
  const post = vi.fn()
  vi.stubGlobal('BroadcastChannel', class { onmessage = null; postMessage = post; close() {} })
  const stop = watchSessionChanges()
  try {
    const response = deferred<Response>()
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(response.promise))
    const logout = logoutCurrentSession()
    setIdentity({ ...alice, csrf_token: 'renewed' })
    response.resolve(new Response(null, { status: 204 }))
    await logout
    expect(currentUser()?.id).toBe('alice')
    expect(post).not.toHaveBeenCalled()
  } finally { stop() }
})

it('completes explicit logout after another request expires the same session', async () => {
  const response = deferred<Response>()
  vi.stubGlobal('fetch', vi.fn().mockReturnValue(response.promise))
  const logout = logoutCurrentSession()
  setIdentity(null)
  response.resolve(new Response(null, { status: 204 }))
  await logout
  expect(currentUser()).toBeNull()
})

it('returns a typed auth error without a JSON response body', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('gateway unavailable', { status: 503 })))
  await expect(authRequest('/auth/me')).rejects.toBeInstanceOf(AuthRequestError)
})
