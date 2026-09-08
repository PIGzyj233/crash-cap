/** Session secrets stay in HttpOnly cookies; only the CSRF proof lives in memory. */
export type UserIdentity = { id: string; username: string; display_name: string; kind: string; role: string; enabled: boolean; must_change_password: boolean }
export type LoginIdentity = { user: UserIdentity; csrf_token: string }
let identity: LoginIdentity | null = null
let retainedUser: UserIdentity | null = null
let enabled = false
let accountGeneration = 0
const pending = new Set<() => void>()
let sessionChannel: BroadcastChannel | null = null
const logoutListeners = new Set<() => void>()
let logoutOperation: { session: LoginIdentity | null; promise: Promise<void> } | null = null

export class AuthRequestError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message)
    this.name = 'AuthRequestError'
  }
}

export function subscribeLogout(listener: () => void) {
  logoutListeners.add(listener)
  return () => { logoutListeners.delete(listener) }
}
export function getLogoutPending() { return !!logoutOperation && logoutOperation.session === identity }
function notifyLogout() { for (const listener of logoutListeners) listener() }

export function enableAuthentication() { enabled = true }
export function currentUser() { return retainedUser }

export function sessionExpirationHandler() {
  const session = identity
  return () => { if (session && identity === session) setIdentity(null) }
}

/** Captures one account lifetime across hashing, network retries and upload polling. */
export function captureAccount() {
  const generation = accountGeneration
  const userId = retainedUser?.id
  return () => {
    if (generation !== accountGeneration || userId !== retainedUser?.id) {
      throw new Error('账号已切换或退出，原账号的操作已停止')
    }
  }
}

export function setIdentity(value: LoginIdentity | null) {
  if (value && retainedUser?.id !== value.user.id) accountGeneration += 1
  identity = value
  if (value) retainedUser = value.user
  // Wake on account changes as well as normal login; restricted sessions cannot replay writes.
  for (const resume of [...pending]) resume()
  window.dispatchEvent(new CustomEvent('crashcap-identity', { detail: value }))
  notifyLogout()
}

export function clearIdentity() {
  accountGeneration += 1
  retainedUser = null
  setIdentity(null)
}

/** Cookies are shared by tabs; notify peers without publishing cookie or CSRF values. */
export function watchSessionChanges() {
  if (typeof BroadcastChannel === 'undefined') return () => {}
  const channel = new BroadcastChannel('crashcap-session')
  sessionChannel = channel
  let active = true
  let revision = 0
  channel.onmessage = event => {
    if (!event.data || typeof event.data !== 'object') return
    const received = ++revision
    const change = event.data as { type?: string; userId?: string }
    if (change.type === 'logout') { clearIdentity(); return }
    if (change.type !== 'login' || typeof change.userId !== 'string') return
    if (retainedUser?.id !== change.userId) clearIdentity()
    else setIdentity(null)
    void authRequest<LoginIdentity>('/auth/me').then(value => { if (active && received === revision) setIdentity(value) }).catch(() => {})
  }
  return () => { active = false; channel.close(); if (sessionChannel === channel) sessionChannel = null }
}

export async function authRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const checkAccount = captureAccount()
  const sentIdentity = identity
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (sentIdentity) headers.set('X-CSRF-Token', sentIdentity.csrf_token)
  const response = await fetch(`/api/v3${path}`, { ...init, headers, credentials: 'same-origin' })
  checkAccount()
  if (!response.ok) {
    if (response.status === 401 && sentIdentity && identity === sentIdentity && !['/auth/login', '/auth/logout'].includes(path)) setIdentity(null)
    const body = await response.json().catch(() => null)
    throw new AuthRequestError(body?.error?.message ?? `请求失败 (${response.status})`, response.status, body?.error?.code)
  }
  const body = response.status === 204 ? undefined as T : await response.json() as T
  checkAccount()
  if (path === '/auth/login') sessionChannel?.postMessage({ type: 'login', userId: (body as LoginIdentity).user.id })
  if (path === '/auth/password') sessionChannel?.postMessage({ type: 'logout' })
  return body
}

/** One explicit logout per session, shared by every UI entry point. */
export function logoutCurrentSession(): Promise<void> {
  if (logoutOperation?.session === identity) return logoutOperation.promise
  const source = identity
  const checkAccount = captureAccount()
  const stillCurrent = () => {
    try { checkAccount(); return !identity || identity === source } catch { return false }
  }
  const operation = { session: source, promise: Promise.resolve() }
  operation.promise = (async () => {
    try {
      await authRequest('/auth/logout', { method: 'POST' })
    } catch (error) {
      if (!stillCurrent()) return
      // A gateway 401 is not evidence that the platform session was revoked.
      if (!(error instanceof AuthRequestError && error.status === 401 && error.code === 'UNAUTHENTICATED')) throw error
    }
    if (!stillCurrent()) return
    clearIdentity()
    sessionChannel?.postMessage({ type: 'logout' })
  })().finally(() => {
    if (logoutOperation === operation) { logoutOperation = null; notifyLogout() }
  })
  logoutOperation = operation
  notifyLogout()
  return operation.promise
}

export async function sessionFetch(fetcher: typeof fetch, input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const userId = retainedUser?.id
  const checkAccount = captureAccount()
  const check = () => { checkAccount(); init.signal?.throwIfAborted() }
  const waitForLogin = () => new Promise<void>((resolve, reject) => {
    const finish = (error?: unknown) => {
      pending.delete(resume)
      init.signal?.removeEventListener('abort', resume)
      if (error) reject(error)
      else resolve()
    }
    const resume = () => {
      try {
        check()
        if (identity && !identity.user.must_change_password) finish()
      } catch (error) { finish(error) }
    }
    pending.add(resume)
    init.signal?.addEventListener('abort', resume, { once: true })
    resume()
  })
  let sentCsrf: string | undefined
  const send = async () => {
    check()
    sentCsrf = identity?.csrf_token
    const headers = new Headers(init.headers)
    if (identity && !['GET', 'HEAD', 'OPTIONS'].includes((init.method ?? 'GET').toUpperCase())) headers.set('X-CSRF-Token', identity.csrf_token)
    const response = await fetcher(input, { ...init, headers, credentials: 'same-origin' })
    // Old responses must never populate the new account’s cache or restart its login flow.
    check()
    return response
  }
  if (enabled && userId && (!identity || identity.user.must_change_password)) await waitForLogin()
  let response = await send()
  while (response.status === 401 && enabled && userId) {
    if (identity?.user.id === userId && identity.csrf_token !== sentCsrf) {
      response = await send()
      continue
    }
    if (identity) setIdentity(null)
    await waitForLogin()
    response = await send()
  }
  return response
}
