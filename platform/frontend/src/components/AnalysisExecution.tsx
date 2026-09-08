import { Collapse,Typography } from 'antd'
import type { AnalysisRunSummary } from '../types'

const stages: Record<string, string> = {
  prepare_core: '准备分析容器与输入文件',
  load_inputs: '读取 DMP 与模块检查结果', materialize_symbols: '准备并校验业务符号',
  analyze_dump: '展开调用栈并查询符号', persist_report: '保存报告与诊断证据', complete: '报告处理完成',
}

export function executionStage(progress: AnalysisRunSummary['progress']): string | null {
  if (!progress || typeof progress.stage !== 'string') return null
  const title = stages[progress.stage] ?? '正在处理'
  return typeof progress.completed === 'number' && typeof progress.total === 'number'
    ? `${title}（${progress.completed}/${progress.total}）` : title
}

export function executionError(run: Pick<AnalysisRunSummary, 'error_code' | 'progress'>): string {
  if (run.progress?.stage === 'persist_report') return '报告保存失败，已保留诊断信息。'
  if (run.error_code?.startsWith('CORE_STAGE_')) return '分析输入准备失败，请检查存储和容器状态。'
  const descriptions: Record<string, string> = {
    FROZEN_SOURCE_FAILED: '符号查询未完成，请查看失败模块与请求诊断。',
    FROZEN_ANALYSIS_FAILED: '报告生成或保存失败，请查看技术详情。',
    INVALID_FROZEN_EVIDENCE: '分析输入的身份或完整性校验未通过。',
    CORRUPT_DUMP: 'DMP 内容损坏，无法生成可信报告。',
    CORE_TIMEOUT: '分析执行超时。',
  }
  return descriptions[run.error_code ?? ''] ?? '本次分析没有生成可用报告，请查看技术详情。'
}

export function ExecutionDetails({ run }: { run: Pick<AnalysisRunSummary, 'error_code' | 'error_detail' | 'progress' | 'diagnostics'> }) {
  if (!run.error_code && !run.diagnostics) return null
  return <Collapse size="small" items={[{ key: 'diagnostics', label: '技术详情与请求诊断', children: <>
    <Typography.Text>{run.error_code ? '失败阶段' : '执行阶段'}：{executionStage(run.progress) ?? '未记录'}</Typography.Text>
    <pre className="json-block">{JSON.stringify({ error_code: run.error_code, detail: run.error_detail, diagnostics: run.diagnostics }, null, 2)}</pre>
  </> }]} />
}
