/** Session secrets stay in HttpOnly cookies; only the CSRF proof lives in memory. */
export type UserIdentity = { id: string; username: string; display_name: string; kind: string; role: string; enabled: boolean; must_change_password: boolean }
export type LoginIdentity = { user: UserIdentity; csrf_token: string }
let identity: LoginIdentity | null = null
let retainedUser: UserIdentity | null = null
let enabled = false
let pending: Array<{ userId: string; resolve: () => void; reject: (error: Error) => void }> = []
export function enableAuthentication() { enabled = true }
export function currentUser() { return retainedUser }
export function setIdentity(value: LoginIdentity | null) {
  identity = value
  if (value) retainedUser = value.user
  if (value && !value.user.must_change_password) {
    const waiting = pending; pending = []
    waiting.forEach(waiter => value.user.id === waiter.userId ? waiter.resolve() : waiter.reject(new Error('账号已切换，原账号的操作已停止')))
  }
  window.dispatchEvent(new CustomEvent('crashcap-identity', { detail: value }))
}
export function clearIdentity() {
  retainedUser = null
  const waiting = pending; pending = []
  waiting.forEach(waiter => waiter.reject(new Error('已退出登录，操作已停止')))
  setIdentity(null)
}
export async function authRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (identity) headers.set('X-CSRF-Token', identity.csrf_token)
  const response = await fetch(`/api/v3${path}`, { ...init, headers, credentials: 'same-origin' })
  if (!response.ok) {
    if (response.status === 401 && identity && path !== '/auth/login') setIdentity(null)
    const body = await response.json().catch(() => null)
    throw new Error(body?.error?.message ?? `请求失败 (${response.status})`)
  }
  return response.status === 204 ? undefined as T : await response.json() as T
}
export async function sessionFetch(fetcher: typeof fetch, input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const userId = retainedUser?.id
  const waitForLogin = () => new Promise<void>((resolve, reject) => pending.push({ userId: userId!, resolve, reject }))
  let sentCsrf: string | undefined
  const send = () => {
    if (enabled && userId && retainedUser?.id !== userId) throw new Error('账号已切换，原账号的操作已停止')
    sentCsrf = identity?.csrf_token
    const headers = new Headers(init.headers)
    if (identity && !['GET', 'HEAD', 'OPTIONS'].includes(init.method ?? 'GET')) headers.set('X-CSRF-Token', identity.csrf_token)
    return fetcher(input, { ...init, headers, credentials: 'same-origin' })
  }
  if (enabled && userId && !identity) await waitForLogin()
  let response = await send()
  while (response.status === 401 && enabled && userId) {
    if (identity?.user.id === userId && identity.csrf_token !== sentCsrf) {
      response = await send()
      continue
    }
    const restored = waitForLogin()
    setIdentity(null)
    await restored
    response = await send()
  }
  return response
}
