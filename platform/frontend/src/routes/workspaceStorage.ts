const LEGACY_WORKSPACE_KEY = 'crash-cap.workspace'
const LAST_WORKSPACE_KEY = 'crash-cap.lastWorkspaceId'

function storage(): Storage | null {
  return typeof window === 'undefined' ? null : window.localStorage
}

export function migrateLegacyWorkspaceStorage(): string | null {
  const target = storage()
  if (!target) return null
  const existing = target.getItem(LAST_WORKSPACE_KEY)
  const legacy = target.getItem(LEGACY_WORKSPACE_KEY)
  if (legacy !== null) {
    try {
      const parsed = JSON.parse(legacy) as { id?: unknown }
      if (!existing && typeof parsed.id === 'string' && parsed.id) {
        target.setItem(LAST_WORKSPACE_KEY, parsed.id)
      }
    } catch {
      // Invalid legacy JSON is simply retired; it was never an authority.
    } finally {
      target.removeItem(LEGACY_WORKSPACE_KEY)
    }
  }
  return target.getItem(LAST_WORKSPACE_KEY)
}

export function getLastWorkspaceId(): string | null {
  return storage()?.getItem(LAST_WORKSPACE_KEY) ?? null
}

export function rememberWorkspace(workspaceId: string): void {
  storage()?.setItem(LAST_WORKSPACE_KEY, workspaceId)
}

export function clearLastWorkspace(workspaceId?: string): void {
  const target = storage()
  if (!target) return
  if (!workspaceId || target.getItem(LAST_WORKSPACE_KEY) === workspaceId) {
    target.removeItem(LAST_WORKSPACE_KEY)
  }
}
