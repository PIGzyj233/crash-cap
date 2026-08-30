import { beforeEach, describe, expect, it } from 'vitest'
import { clearLastWorkspace, getLastWorkspaceId, migrateLegacyWorkspaceStorage, rememberWorkspace } from './workspaceStorage'

describe('Workspace browser storage migration', () => {
  beforeEach(() => localStorage.clear())

  it('keeps only the stable ID from the legacy full Workspace JSON', () => {
    localStorage.setItem('crash-cap.workspace', JSON.stringify({ id: 'wsp_legacy', name: 'stale-name', retention_days: 999 }))
    expect(migrateLegacyWorkspaceStorage()).toBe('wsp_legacy')
    expect(localStorage.getItem('crash-cap.workspace')).toBeNull()
    expect(localStorage.getItem('crash-cap.lastWorkspaceId')).toBe('wsp_legacy')
  })

  it('clears only the matching invalid shortcut', () => {
    rememberWorkspace('wsp_current')
    clearLastWorkspace('wsp_other')
    expect(getLastWorkspaceId()).toBe('wsp_current')
    clearLastWorkspace('wsp_current')
    expect(getLastWorkspaceId()).toBeNull()
  })
})
