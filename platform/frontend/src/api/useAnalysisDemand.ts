import { useQuery,useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { demandPollingInterval } from './analysisDemand'
import { useApi } from './context'
import { usePageVisible } from './hooks'

export function useAnalysisDemand(workspaceId: string, occurrenceId: string, enabled: boolean) {
  const api = useApi()
  const visible = usePageVisible()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['analysis-demand', workspaceId, occurrenceId],
    queryFn: () => api.getAnalysisDemand(workspaceId, occurrenceId),
    enabled,
    retry: false,
    refetchInterval: (current) => demandPollingInterval(current.state.data, visible, current.state.status === 'error'),
  })
  const demand = query.data
  useEffect(() => {
    if (demand) void queryClient.invalidateQueries({ queryKey: ['occurrence', occurrenceId] })
  }, [queryClient, occurrenceId, demand?.demand_id, demand?.generation, demand?.retry_attempt, demand?.run_id, demand?.state])
  return query
}
