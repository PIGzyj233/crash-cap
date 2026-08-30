import type { AnalysisRunSummary, AnalysisStatus } from '../types'

const TERMINAL_STATUSES = new Set<AnalysisStatus>([
  'COMPLETE',
  'PARTIAL',
  'FAILED',
  'REJECTED',
  'CANCELLED',
  'TIMEOUT',
  'OOM',
])

const ANALYZING_STATUSES = new Set<AnalysisStatus>([
  'VALIDATING',
  'INSPECTED',
  'MATCHING_SYMBOLS',
  'WAITING_FOR_SYMBOLS',
  'SYMBOLS_READY',
  'ANALYZING',
  'NORMALIZING',
  'GROUPING',
])

export function getPollingInterval(status: AnalysisStatus | null | undefined): number | false {
  if (!status || TERMINAL_STATUSES.has(status)) return false
  if (status === 'QUEUED' || status === 'UPLOADED') return 10_000
  if (ANALYZING_STATUSES.has(status)) return 2_000
  return false
}

export function isTerminalStatus(status: AnalysisStatus | null | undefined): boolean {
  return Boolean(status && TERMINAL_STATUSES.has(status))
}

export function getOccurrencePollingInterval(
  current: Pick<AnalysisRunSummary, 'id' | 'status'> | null | undefined,
  latest: Pick<AnalysisRunSummary, 'id' | 'status'> | null | undefined,
): number | false {
  if (latest && latest.id !== current?.id && !isTerminalStatus(latest.status)) {
    return getPollingInterval(latest.status)
  }
  return getPollingInterval(current?.status ?? latest?.status)
}

export function statusLabel(status: AnalysisStatus | null | undefined): string {
  const labels: Record<string, string> = {
    UPLOADED: '已上传',
    VALIDATING: '校验中',
    INSPECTED: '已检查',
    MATCHING_SYMBOLS: '匹配符号',
    WAITING_FOR_SYMBOLS: '等待符号',
    SYMBOLS_READY: '符号就绪',
    QUEUED: '排队中',
    ANALYZING: '分析中',
    NORMALIZING: '结果整理中',
    GROUPING: '分组中',
    COMPLETE: '完成',
    PARTIAL: '部分完成',
    FAILED: '失败',
    REJECTED: '已拒绝',
    CANCELLED: '已取消',
    TIMEOUT: '超时',
    OOM: '内存不足',
    system_symbol_pending: '等待公共符号',
    system_symbol_failed: '公共符号缺失',
    symbolicator_failed: '业务符号解析失败',
  }
  return status ? labels[status] ?? status : '尚未开始'
}
