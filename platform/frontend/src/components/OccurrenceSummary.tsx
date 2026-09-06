import { Space,Tag,Typography } from 'antd'
import { Link } from 'react-router-dom'
import { routePaths } from '../routes/routePaths'
import type { OccurrenceListItem } from '../types'
import { DataTable } from './DataTable'
import { StatusTag,SymbolText } from './ui'

const { Text } = Typography

export function OccurrenceStatusSummary({ occurrence }: { occurrence: OccurrenceListItem }) {
  const current = occurrence.current_analysis
  const latest = occurrence.latest_attempt
  const failed = latest && ['FAILED', 'REJECTED', 'CANCELLED', 'TIMEOUT', 'OOM'].includes(latest.status)
  const updateLabels: Record<string, string> = { preparing: '正在准备更新', coalescing: '等待合并更新', queued: '更新已排队', running: '正在更新', retained: '保留原报告', needs_review: '需要复核', retry_wait: '等待自动重试', retry_exhausted: '重试已用尽', cannot_recompute: '无法重新分析', paused: '更新已暂停' }
  return <Space direction="vertical" size={2}>
    {current ? <span><Text type="secondary">当前报告 </Text><StatusTag status={current.status} /></span> : <Tag>尚无可用报告</Tag>}
    {latest && latest.id !== current?.id ? <span><Text type={failed ? 'danger' : 'secondary'}>{failed ? '最近尝试失败' : '最近分析'} </Text><StatusTag status={latest.status} /></span> : !latest ? <Text type="secondary">等待创建分析</Text> : null}
    {occurrence.analysis_update_state && updateLabels[occurrence.analysis_update_state] && <Tag color={occurrence.analysis_update_state === 'needs_review' ? 'orange' : undefined}>{updateLabels[occurrence.analysis_update_state]}</Tag>}
  </Space>
}

export function OccurrenceCompactSummary({ occurrence }: { occurrence: OccurrenceListItem }) {
  const title = occurrence.summary?.exception_name ?? occurrence.summary?.exception_code ?? '尚无可用报告'
  return <Link className="occurrence-summary-link" to={routePaths.occurrence(occurrence.workspace_id, occurrence.id)}>
    <span className="occurrence-summary-main"><Text strong>{title}</Text><Text type="secondary">{occurrence.summary?.fault_module ?? '—'}!{occurrence.summary?.top_function ?? '—'}</Text><Text type="secondary">版本 {occurrence.version ?? '未声明版本'}</Text></span>
    <span className="occurrence-summary-meta"><Text>{new Date(occurrence.occurred_at).toLocaleString('zh-CN')}</Text><OccurrenceStatusSummary occurrence={occurrence} /></span>
  </Link>
}

export function OccurrenceSummaryTable({ workspaceId, items }: { workspaceId: string; items: OccurrenceListItem[] }) {
  return <DataTable<OccurrenceListItem> rowKey="id" dataSource={items} minWidth={640} pagination={false} columns={[
    { title: '异常与故障位置', key: 'conclusion', render: (_, row) => <Space direction="vertical" size={4}>
      <Link to={routePaths.occurrence(workspaceId, row.id)}><Text strong>{row.summary?.exception_name ?? row.summary?.exception_code ?? '尚无可用报告'}</Text><br /><Text type="secondary">{row.summary?.fault_module ?? '—'}!<SymbolText value={row.summary?.top_function} head={24} tail={12} /></Text></Link>
      {row.group ? <Link to={routePaths.group(workspaceId, row.group.id)}>分组：{row.group.title}</Link> : row.summary?.crash_type === 'crash' ? <Text type="secondary">尚未精确分组</Text> : null}
    </Space> },
    { title: '版本', dataIndex: 'version', width: 130, render: (value: string | null) => value ?? '未声明版本' },
    { title: '发生时间', dataIndex: 'occurred_at', width: 155, render: (value: string) => new Date(value).toLocaleString('zh-CN') },
    { title: '报告与分析状态', key: 'status', width: 190, render: (_, row) => <OccurrenceStatusSummary occurrence={row} /> },
  ]} />
}
