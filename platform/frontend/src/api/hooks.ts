import { useEffect, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useApi } from './context'
import { CrashCapApiError } from './client'
import { getOccurrencePollingInterval, getPollingInterval, isTerminalStatus } from './polling'
import { mergeSymbolHealthRows } from './symbolHealth'
import type { BuildCreateInput, BuildManifestInput, OccurrenceListParams, OccurrenceProgressEvent } from '../types'

export function usePageVisible() {
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || document.visibilityState === 'visible')
  useEffect(() => {
    const onVisibilityChange = () => setVisible(document.visibilityState === 'visible')
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [])
  return visible
}

export function useWorkspaces() {
  const api = useApi()
  return useQuery({ queryKey: ['workspaces'], queryFn: api.listWorkspaces })
}

export function useWorkspace(workspaceId: string | undefined) {
  const api = useApi()
  return useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: () => api.getWorkspace(workspaceId!),
    enabled: Boolean(workspaceId),
    retry: (failureCount, error) => !(error instanceof CrashCapApiError && error.status === 404) && failureCount < 1,
  })
}

export function usePlatformOverview(params?: { from?: string; to?: string }) {
  const api = useApi()
  return useQuery({ queryKey: ['platform-overview', params], queryFn: () => api.getPlatformOverview(params) })
}

export function useOccurrences(workspaceId: string | undefined, params: OccurrenceListParams) {
  const api = useApi()
  return useQuery({
    queryKey: ['occurrences', workspaceId, params],
    queryFn: () => api.listOccurrences(workspaceId!, params),
    enabled: Boolean(workspaceId),
    placeholderData: keepPreviousData,
  })
}

export function useWorkspaceOverview(workspaceId: string | undefined, params?: { from?: string; to?: string }) {
  const api = useApi()
  return useQuery({
    queryKey: ['workspace-overview', workspaceId, params],
    queryFn: () => api.getWorkspaceOverview(workspaceId!, params),
    enabled: Boolean(workspaceId),
  })
}

export function useBuilds(workspaceId: string | undefined) {
  const api = useApi()
  return useQuery({ queryKey: ['builds', workspaceId], queryFn: () => api.listBuilds(workspaceId!), enabled: Boolean(workspaceId) })
}

export function useBuild(buildId: string | undefined) {
  const api = useApi()
  return useQuery({
    queryKey: ['build', buildId],
    queryFn: () => api.getBuild(buildId!),
    enabled: Boolean(buildId),
    retry: (failureCount, error) => !(error instanceof CrashCapApiError && error.status === 404) && failureCount < 1,
  })
}

export function useBuildPublicationStatus(buildId: string | undefined, enabled = true) {
  const api = useApi()
  const visible = usePageVisible()
  return useQuery({
    queryKey: ['build-publication-status', buildId],
    queryFn: () => api.getBuildPublicationStatus(buildId!),
    enabled: Boolean(buildId && enabled),
    refetchInterval: (query) => {
      if (!visible) return false
      return ['uploading', 'verifying'].includes(query.state.data?.status ?? '') ? 2_000 : false
    },
  })
}

export function useArtifactProducers() {
  const api = useApi()
  return useQuery({ queryKey: ['artifact-producers'], queryFn: api.getArtifactProducers })
}

export function useOccurrence(occurrenceId: string | undefined, pollingEnabled = true) {
  const api = useApi()
  const visible = usePageVisible()
  return useQuery({
    queryKey: ['occurrence', occurrenceId],
    queryFn: () => api.getOccurrence(occurrenceId!),
    enabled: Boolean(occurrenceId),
    retry: (failureCount, error) => !(error instanceof CrashCapApiError && error.status === 404) && failureCount < 1,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      if (!visible || !pollingEnabled) return false
      const data = query.state.data
      return getOccurrencePollingInterval(data?.current_analysis, data?.latest_attempt)
    },
  })
}

export function useOccurrenceProgress(occurrenceId: string | undefined) {
  const api = useApi()
  const queryClient = useQueryClient()
  const visible = usePageVisible()
  const [mode, setMode] = useState<'connecting' | 'sse' | 'polling' | 'terminal'>(() =>
    typeof EventSource === 'undefined' ? 'polling' : 'connecting',
  )
  useEffect(() => {
    if (!occurrenceId || !visible || typeof EventSource === 'undefined') {
      setMode('polling')
      return
    }
    const source = new EventSource(api.getOccurrenceEventsUrl(occurrenceId))
    setMode('connecting')
    source.onopen = () => setMode('sse')
    source.addEventListener('analysis-progress', (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent<string>).data) as OccurrenceProgressEvent
        void queryClient.invalidateQueries({ queryKey: ['occurrence', occurrenceId] })
        if (isTerminalStatus(payload.run.status)) {
          setMode('terminal')
          source.close()
        }
      } catch {
        setMode('polling')
        source.close()
      }
    })
    source.onerror = () => {
      setMode('polling')
      source.close()
    }
    return () => source.close()
  }, [api, occurrenceId, queryClient, visible])
  return mode
}

export function useOccurrenceAnalysis(occurrenceId: string | undefined, runId: string | undefined, enabled: boolean) {
  const api = useApi()
  return useQuery({
    queryKey: ['occurrence-analysis', occurrenceId, runId],
    queryFn: () => api.getOccurrenceAnalysis(occurrenceId!, runId),
    enabled: Boolean(occurrenceId && runId && enabled),
    staleTime: Infinity,
  })
}

export function useThreads(occurrenceId: string | undefined, enabled: boolean, runId?: string) {
  const api = useApi()
  return useQuery({ queryKey: ['occurrence-threads', occurrenceId, runId], queryFn: () => api.getOccurrenceThreads(occurrenceId!, runId), enabled: Boolean(occurrenceId && enabled), staleTime: Infinity })
}

export function useModules(occurrenceId: string | undefined, enabled: boolean, runId?: string) {
  const api = useApi()
  return useQuery({ queryKey: ['occurrence-modules', occurrenceId, runId], queryFn: () => api.getOccurrenceModules(occurrenceId!, runId), enabled: Boolean(occurrenceId && enabled), staleTime: Infinity })
}

export function useSymbolHealth(workspaceId: string | undefined) {
  const api = useApi()
  return useQuery({
    queryKey: ['symbol-health', workspaceId],
    queryFn: async () => {
      const [inventory, affected] = await Promise.all([
        api.getSymbolHealth(workspaceId!),
        api.getMissingSymbols(workspaceId!),
      ])
      return mergeSymbolHealthRows(inventory, affected)
    },
    enabled: Boolean(workspaceId),
  })
}

export function useGroups(workspaceId: string | undefined) {
  const api = useApi()
  return useQuery({ queryKey: ['groups', workspaceId], queryFn: () => api.listGroups(workspaceId!, { group_type: 'exact' }), enabled: Boolean(workspaceId) })
}

export function useGroup(groupId: string | undefined) {
  const api = useApi()
  return useQuery({
    queryKey: ['group', groupId],
    queryFn: () => api.getGroup(groupId!),
    enabled: Boolean(groupId),
    retry: (failureCount, error) => !(error instanceof CrashCapApiError && error.status === 404) && failureCount < 1,
  })
}

export function useCreateWorkspace() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.createWorkspace,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      void queryClient.invalidateQueries({ queryKey: ['platform-overview'] })
    },
  })
}

export function useCreateBuild(workspaceId: string) {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: BuildCreateInput) => api.createBuild(workspaceId, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['builds', workspaceId] }),
  })
}

export function usePutManifest(buildId: string, workspaceId: string) {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (manifest: BuildManifestInput) => api.putManifest(buildId, manifest),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['build', buildId] })
      queryClient.invalidateQueries({ queryKey: ['builds', workspaceId] })
    },
  })
}

export function useReprocessOccurrence(occurrenceId: string) {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { force: boolean; reported_build_id?: string } = { force: false }) => api.reprocessOccurrence(occurrenceId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['occurrence', occurrenceId] })
      void queryClient.invalidateQueries({ queryKey: ['occurrences'] })
      void queryClient.invalidateQueries({ queryKey: ['platform-overview'] })
      void queryClient.invalidateQueries({ queryKey: ['workspace-overview'] })
    },
  })
}
