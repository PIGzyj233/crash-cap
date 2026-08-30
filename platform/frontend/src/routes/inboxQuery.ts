import type { AnalysisStatus, OccurrenceListParams, ResolutionMethod } from '../types'

const CRASH_TYPES = new Set(['crash', 'hang', 'unknown', 'no_current'])
const ANALYSIS_STATUSES = new Set<string>([
  'UPLOADED', 'VALIDATING', 'INSPECTED', 'MATCHING_SYMBOLS', 'WAITING_FOR_SYMBOLS',
  'SYMBOLS_READY', 'QUEUED', 'ANALYZING', 'NORMALIZING', 'GROUPING', 'COMPLETE',
  'PARTIAL', 'FAILED', 'REJECTED', 'CANCELLED', 'TIMEOUT', 'OOM',
])
const RESOLUTION_METHODS = new Set<string>([
  'reported', 'auto_unique', 'manual', 'ambiguous', 'unresolved', 'no_current',
])
const GROUPING = new Set(['exact', 'unclassified', 'no_current'])

export interface ParsedInboxQuery {
  filters: OccurrenceListParams
  canonical: URLSearchParams
  changed: boolean
}

export function parseInboxQuery(input: URLSearchParams): ParsedInboxQuery {
  const filters: OccurrenceListParams = {}
  const crashType = enumValue(input.get('crash_type'), CRASH_TYPES)
  const latestStatus = enumValue(input.get('latest_status'), ANALYSIS_STATUSES)
  const resolutionMethod = enumValue(input.get('resolution_method'), RESOLUTION_METHODS)
  const grouping = enumValue(input.get('grouping'), GROUPING)
  const from = timestampValue(input.get('from'))
  const to = timestampValue(input.get('to'))
  const q = textValue(input.get('q'), 128)
  const version = textValue(input.get('version'), 200, false)
  const buildId = textValue(input.get('build_id'), 128, false)
  const cursor = textValue(input.get('cursor'), 2048, false)

  if (crashType) filters.crash_type = crashType as OccurrenceListParams['crash_type']
  if (latestStatus) filters.latest_status = latestStatus as AnalysisStatus
  if (resolutionMethod) filters.resolution_method = resolutionMethod as ResolutionMethod | 'no_current'
  if (grouping) filters.grouping = grouping as OccurrenceListParams['grouping']
  if (from && to && new Date(from) > new Date(to)) {
    // Drop an inverted range together; retaining only one side would silently
    // change the user's intended interval.
  } else {
    if (from) filters.from = from
    if (to) filters.to = to
  }
  if (q) filters.q = q
  if (version) filters.version = version
  if (buildId) filters.build_id = buildId
  if (cursor) filters.cursor = cursor

  const canonical = serializeInboxQuery(filters)
  return { filters, canonical, changed: canonical.toString() !== input.toString() }
}

export function serializeInboxQuery(filters: OccurrenceListParams): URLSearchParams {
  const output = new URLSearchParams()
  const entries: Array<[keyof OccurrenceListParams, string | number | undefined]> = [
    ['from', filters.from],
    ['to', filters.to],
    ['crash_type', filters.crash_type],
    ['latest_status', filters.latest_status],
    ['resolution_method', filters.resolution_method],
    ['version', filters.version],
    ['build_id', filters.build_id],
    ['grouping', filters.grouping],
    ['q', filters.q],
    ['cursor', filters.cursor],
  ]
  entries.forEach(([key, value]) => {
    if (value !== undefined && value !== '') output.set(key, String(value))
  })
  return output
}

function enumValue(value: string | null, allowed: Set<string>): string | undefined {
  return value !== null && allowed.has(value) ? value : undefined
}

function timestampValue(value: string | null): string | undefined {
  if (!value || !/(?:z|[+-]\d{2}:\d{2})$/i.test(value)) return undefined
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? undefined : parsed.toISOString()
}

function textValue(value: string | null, maxLength: number, trim = true): string | undefined {
  if (value === null || value.length > maxLength) return undefined
  const normalized = trim ? value.trim() : value
  return normalized || undefined
}
