const segment = (value: string) => encodeURIComponent(value)

export const routePaths = {
  home: '/',
  symbolImports: '/symbol-imports',
  workspaces: '/workspaces',
  workspace: (workspaceId: string) => `/w/${segment(workspaceId)}`,
  overview: (workspaceId: string) => `/w/${segment(workspaceId)}/overview`,
  occurrences: (workspaceId: string) => `/w/${segment(workspaceId)}/occurrences`,
  occurrence: (workspaceId: string, occurrenceId: string) => `/w/${segment(workspaceId)}/occurrences/${segment(occurrenceId)}`,
  upload: (workspaceId: string) => `/w/${segment(workspaceId)}/upload`,
  builds: (workspaceId: string) => `/w/${segment(workspaceId)}/builds`,
  build: (workspaceId: string, buildId: string) => `/w/${segment(workspaceId)}/builds/${segment(buildId)}`,
  symbols: (workspaceId: string) => `/w/${segment(workspaceId)}/symbols`,
  groups: (workspaceId: string) => `/w/${segment(workspaceId)}/groups`,
  group: (workspaceId: string, groupId: string) => `/w/${segment(workspaceId)}/groups/${segment(groupId)}`,
  developer: (workspaceId: string) => `/w/${segment(workspaceId)}/developer`,
} as const
