import type { components } from '../generated/openapi'

export type AnalysisDemand = components['schemas']['DemandStatusResponse']

export function demandPollingInterval(demand: AnalysisDemand | null | undefined, visible: boolean, failed: boolean): number | false {
  if (!visible || failed) return false
  return demand && ['preparing', 'coalescing', 'queued', 'running', 'retry_wait'].includes(demand.state) ? 2_000 : 10_000
}
