import { Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { OccurrenceListItem } from '../types'
import { routePaths } from '../routes/routePaths'
import { DataTable } from './DataTable'
import { HashValue, StatusTag, SymbolText } from './ui'

const { Text } = Typography

export function OccurrenceStatusSummary({ occurrence }: { occurrence: OccurrenceListItem }) {
  const current = occurrence.current_analysis
  const latest = occurrence.latest_attempt
  return <Space direction="vertical" size={2}>
    {current ? <span><Text type="secondary">Current </Text><StatusTag status={current.status} /></span> : <Tag>尚无可用分析</Tag>}
    {latest ? <span><Text type="secondary">Latest </Text><StatusTag status={latest.status} />{current?.id === latest.id ? <Text type="secondary"> 同一 Run</Text> : null}</span> : <Text type="secondary">尚未创建 Run</Text>}
  </Space>
}

export function OccurrenceCompactSummary({ occurrence }: { occurrence: OccurrenceListItem }) {
  const title = occurrence.summary?.exception_name ?? occurrence.summary?.exception_code ?? '尚无可用分析'
  return <Link className="occurrence-summary-link" to={routePaths.occurrence(occurrence.workspace_id, occurrence.id)}>
    <span className="occurrence-summary-main"><Text strong>{title}</Text><Text type="secondary">{occurrence.summary?.fault_module ?? '—'}!{occurrence.summary?.top_function ?? '—'}</Text></span>
    <span className="occurrence-summary-meta"><Text>{new Date(occurrence.occurred_at).toLocaleString('zh-CN')}</Text><OccurrenceStatusSummary occurrence={occurrence} /></span>
  </Link>
}

export function OccurrenceSummaryTable({ workspaceId, items }: { workspaceId: string; items: OccurrenceListItem[] }) {
  return <DataTable<OccurrenceListItem>
    rowKey="id"
    dataSource={items}
    minWidth={1420}
    pagination={false}
    columns={[
      { title: '时间', dataIndex: 'occurred_at', width: 190, render: (value: string, row) => <Link to={routePaths.occurrence(workspaceId, row.id)}><Text>{new Date(value).toLocaleString('zh-CN')}</Text><br /><Tag>{row.time_source}</Tag></Link> },
      { title: '当前结论', key: 'conclusion', width: 240, render: (_, row) => row.summary ? <Link to={routePaths.occurrence(workspaceId, row.id)}><Text strong>{row.summary.exception_name ?? row.summary.exception_code ?? row.summary.crash_type}</Text><br /><Tag color={row.summary.crash_type === 'crash' ? 'red' : row.summary.crash_type === 'hang' ? 'orange' : 'default'}>{row.summary.crash_type}</Tag>{row.summary.access_type && <Tag>{row.summary.access_type}</Tag>}</Link> : <Link to={routePaths.occurrence(workspaceId, row.id)}>尚无可用分析</Link> },
      { title: 'Current / Latest', key: 'status', width: 220, render: (_, row) => <OccurrenceStatusSummary occurrence={row} /> },
      { title: '顶部位置', key: 'top', width: 260, render: (_, row) => <span><Text>{row.summary?.fault_module ?? '—'}!</Text><SymbolText value={row.summary?.top_function} head={28} tail={14} /></span> },
      { title: 'Version / Build', key: 'build', width: 230, render: (_, row) => row.current_analysis ? <span><Text>{row.summary?.version ?? '未知 Version'}</Text><br /><StatusTag status={row.current_analysis.resolution_method} /> <HashValue value={row.current_analysis.resolved_build_id} length={12} /></span> : <Text type="secondary">N/A</Text> },
      { title: '分组', key: 'group', width: 180, render: (_, row) => !row.current_analysis ? <Text type="secondary">N/A</Text> : row.group ? <Link to={routePaths.group(workspaceId, row.group.id)}>{row.group.title}</Link> : <Tag color="orange">Unclassified</Tag> },
      { title: '质量', key: 'quality', width: 100, align: 'right', render: (_, row) => row.current_analysis?.quality_score == null ? <Text type="secondary">N/A</Text> : <Text strong>{Math.round(row.current_analysis.quality_score * 100)}%</Text> },
    ]}
  />
}
