import { useLocation,useSearchParams } from 'react-router-dom'

function readMap(key: string): Record<string, string> {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(key) ?? '{}')
    return value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).filter(([, cursor]) => typeof cursor === 'string')) : {}
  } catch { return {} }
}

/** Keep the cursor chain separate from browser history, including direct/reloaded URLs. */
export function useCursorNavigation() {
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const filters = new URLSearchParams(params); filters.delete('cursor'); filters.sort()
  const key = `crashcap.cursors:${location.pathname}?${filters}`
  const cursor = params.get('cursor')
  const setCursor = (value?: string | null) => {
    const next = new URLSearchParams(params)
    if (value) next.set('cursor', value); else next.delete('cursor')
    setParams(next)
  }
  return {
    hasPrevious: Boolean(cursor),
    next: (value: string) => {
      try { sessionStorage.setItem(key, JSON.stringify({ ...readMap(key), [value]: cursor ?? '' })) } catch { /* Storage is optional. */ }
      setCursor(value)
    },
    previous: () => setCursor(cursor ? readMap(key)[cursor] : undefined),
  }
}

export function rememberList(path: string) {
  try { sessionStorage.setItem(`crashcap.list:${path.split('?')[0]}`, path) } catch { /* Storage is optional. */ }
}

export function lastList(path: string): string {
  try {
    const value = sessionStorage.getItem(`crashcap.list:${path}`)
    return value?.split('?')[0] === path ? value : path
  } catch { return path }
}
