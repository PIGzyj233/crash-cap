import { Alert,Space,Typography } from 'antd'

export interface DemandStatusView {
  state: string
  not_before: string | null
  withdrawn_basis_pair_ids?: string[] | null
}

const states: Record<string, { title: string; description: string; type: 'info' | 'success' | 'warning' }> = {
  preparing: { title: '正在准备分析', description: '正在检查 DMP 和可用符号。', type: 'info' },
  coalescing: { title: '等待合并更新', description: '正在合并近期符号或归属变化。30/60 秒是合并等待规则，不是报告完成时限。', type: 'info' },
  queued: { title: '已排队', description: '等待可用分析容量，完成时间取决于队列和 DMP 大小。', type: 'info' },
  running: { title: '正在分析', description: '正在生成候选报告，完成后会检查是否更新当前报告。', type: 'info' },
  updated: { title: '报告已更新', description: '本次分析已更新当前报告。', type: 'success' },
  retained: { title: '保留原报告', description: '本次候选结果未替换当前报告，可在分析历史中查看原因。', type: 'info' },
  needs_review: { title: '需要复核', description: '结果或符号证据需要进一步检查，当前报告保持不变。', type: 'warning' },
  retry_wait: { title: '等待重试', description: '本次未能完成更新，将按有限重试计划再次尝试。', type: 'info' },
  retry_exhausted: { title: '自动重试已用尽', description: '请检查失败原因后再安排分析，系统不会无限重试。', type: 'warning' },
  cannot_recompute: { title: '无法重新分析', description: '重新分析所需的 DMP 已不可用，已有历史报告仍可查看。', type: 'warning' },
  paused: { title: '自动分析已暂停', description: '需求已保留，恢复后再继续处理。', type: 'info' },
}

export function AnalysisDemandStatus({ demand }: { demand: DemandStatusView | null }) {
  if (!demand) return null
  const status = states[demand.state] ?? { title: '分析状态待确认', description: '暂时无法识别分析状态，请刷新后重试。', type: 'warning' as const }
  const date = demand.not_before ? new Date(demand.not_before) : null
  const showDue = ['coalescing', 'retry_wait'].includes(demand.state) && date && Number.isFinite(date.getTime())
  const withdrawn = (demand.withdrawn_basis_pair_ids?.length ?? 0) > 0
  return <div role="status" aria-live="polite">
    <Alert showIcon type={withdrawn ? 'warning' : status.type} message={withdrawn ? '当前报告使用的符号依据已停用' : status.title} description={
      <Space direction="vertical" size={4}>
        <span>{status.description}</span>
        {withdrawn && <span>当前报告使用的 {demand.withdrawn_basis_pair_ids!.length} 个配对已被提供方停用。历史结果保留，但这些依据不能继续视为有效；可在模块的符号选择中查看提供方记录。</span>}
        {showDue && <Typography.Text type="secondary">最早重新检查时间：{date.toLocaleString('zh-CN')}（不是报告完成时间）</Typography.Text>}
      </Space>
    } />
  </div>
}
