const segment = (value: string) => encodeURIComponent(value)

export const routePaths = {
  home: '/',
  platformUpload: '/upload',
  platformArtifacts: '/artifacts',
  platformArtifact: (id: string) => `/artifacts/${segment(id)}`,
  workspaces: '/workspaces',
  workspace: (workspaceId: string) => `/w/${segment(workspaceId)}`,
  overview: (workspaceId: string) => `/w/${segment(workspaceId)}/overview`,
  occurrences: (workspaceId: string) => `/w/${segment(workspaceId)}/occurrences`,
  occurrence: (workspaceId: string, occurrenceId: string) => `/w/${segment(workspaceId)}/occurrences/${segment(occurrenceId)}`,
  upload: (workspaceId: string) => `/w/${segment(workspaceId)}/upload`,
  artifacts: (workspaceId: string) => `/w/${segment(workspaceId)}/artifacts`,
  artifact: (workspaceId: string, id: string) => `/w/${segment(workspaceId)}/artifacts/${segment(id)}`,
  symbols: (workspaceId: string) => `/w/${segment(workspaceId)}/symbols`,
  symbolIssue: (workspaceId: string, id: string) => `/w/${segment(workspaceId)}/symbols/${segment(id)}`,
  groups: (workspaceId: string) => `/w/${segment(workspaceId)}/groups`,
  group: (workspaceId: string, groupId: string) => `/w/${segment(workspaceId)}/groups/${segment(groupId)}`,
  developer: (workspaceId: string) => `/w/${segment(workspaceId)}/developer`,
} as const

export function uploadPath(workspaceId?: string, options: { intent?: 'dump' | 'symbols'; issue?: string; returnTo?: string; target?: string } = {}) {
  const query = new URLSearchParams()
  Object.entries(options).forEach(([key, value]) => { if (value) query.set(key, value) })
  return `${workspaceId ? routePaths.upload(workspaceId) : routePaths.platformUpload}${query.size ? `?${query}` : ''}`
}

export function safeReturnPath(value: string | null, workspaceId?: string): string | undefined {
  if (!value || !value.startsWith('/') || value.startsWith('//') || /[\\\r\n]/.test(value)) return undefined
  const path = value.split('?')[0]
  if (workspaceId) return path.startsWith(`/w/${segment(workspaceId)}/`) && !path.endsWith('/upload') ? value : undefined
  return path === '/' || path === '/workspaces' || path === '/artifacts' || path.startsWith('/artifacts/') ? value : undefined
}
