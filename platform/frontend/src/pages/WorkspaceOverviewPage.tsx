import { LinkButton } from '../components/LinkButton'
import { ArrowRightOutlined,ClockCircleOutlined,WarningOutlined,CodeOutlined,PartitionOutlined } from '@ant-design/icons'
import { Button,Card,Input,List,Segmented,Space,Tag,Typography } from 'antd'
import { useMemo,useState } from 'react'
import { Link,useSearchParams } from 'react-router-dom'
import { useWorkspaceOverview } from '../api/hooks'
import { OccurrenceCompactSummary } from '../components/OccurrenceSummary'
import { EmptyState,ErrorState,LoadingState,MetricCard,PageTitle } from '../components/ui'
import { routePaths,uploadPath } from '../routes/routePaths'
import type { OccurrenceListParams,Workspace } from '../types'
import { serializeInboxQuery } from '../routes/inboxQuery'

export function WorkspaceOverviewPage({ workspace }: { workspace: Workspace; onOpenOccurrence?: (id: string) => void; onOpenGroup?: (id: string) => void }) {
  const [params, setParams] = useSearchParams()
  const [now] = useState(() => new Date())
  const [custom, setCustom] = useState({ from: '', to: '' })
  const period = params.get('period') ?? '7'
  const window = useMemo(() => {
    const from = params.get('from'); const to = params.get('to')
    if (period === 'custom' && from && to && Number.isFinite(Date.parse(from)) && Number.isFinite(Date.parse(to))) return { from, to }
    return { from: new Date(now.getTime() - (period === '30' ? 30 : 7) * 86400000).toISOString(), to: now.toISOString() }
  }, [params, period, now])
  const query = useWorkspaceOverview(workspace.id, window)
  if (query.isLoading) return <LoadingState rows={6} title />
  if (query.isError || !query.data) return <ErrorState description="概览加载失败" onRetry={() => void query.refetch()} />
  const data = query.data
  const inbox = (filters: OccurrenceListParams = {}) => `${routePaths.occurrences(workspace.id)}?${serializeInboxQuery({ ...window, ...filters })}`
  const attention = data.attention
  const metrics = [
    { label: '分析中', value: attention.in_progress, key: 'in_progress', icon: <ClockCircleOutlined />, tone: 'blue', hint: '查看正在处理的记录' },
    { label: '最近分析失败', value: attention.latest_attempt_failed, key: 'latest_attempt_failed', icon: <WarningOutlined />, tone: 'red', hint: '已有报告仍可继续查看' },
    { label: '符号受影响', value: attention.symbol_affected_occurrences, key: 'symbol_affected', icon: <CodeOutlined />, tone: 'orange', hint: '当前报告中缺失或不匹配的符号' },
    { label: '未分组崩溃', value: attention.unclassified_crashes, key: 'unclassified', icon: <PartitionOutlined />, tone: 'neutral', hint: '尚无足够证据精确归组' },
  ] as const
  return <div>
    <PageTitle kicker="WORKSPACE" title={workspace.display_name ?? workspace.name} description="从待处理事项开始，查看当前报告与分析进展。" extra={<Segmented aria-label="统计时间范围" value={period} options={[{ label: '最近 7 天', value: '7' }, { label: '最近 30 天', value: '30' }, { label: '自定义', value: 'custom' }]} onChange={value => setParams({ period: value })} />} />
    {period === 'custom' && <Space wrap className="section-card"><label>开始日期<Input aria-label="开始日期" type="date" value={custom.from} onChange={e => setCustom({ ...custom, from: e.target.value })} /></label><label>结束日期<Input aria-label="结束日期" type="date" value={custom.to} onChange={e => setCustom({ ...custom, to: e.target.value })} /></label><Button disabled={!custom.from || !custom.to || custom.from > custom.to} onClick={() => setParams({ period: 'custom', from: new Date(`${custom.from}T00:00:00`).toISOString(), to: new Date(`${custom.to}T23:59:59.999`).toISOString() })}>应用时间范围</Button></Space>}
    <Typography.Paragraph type="secondary">{new Date(window.from).toLocaleDateString()} — {new Date(window.to).toLocaleDateString()} · 按崩溃发生时间统计；重新分析不会增加崩溃次数</Typography.Paragraph>
    {data.total_occurrences === 0 ? <Card className="section-card onboarding-card"><Typography.Title level={3}>开始分析第一份崩溃报告</Typography.Title><Typography.Paragraph type="secondary">{data.total_artifact_entries ? `已入库 ${data.total_artifact_entries} 份程序或符号文件。上传 DMP 后即可查看分析结果。` : '上传 DMP 查看崩溃位置；上传对应程序和 PDB，可以补全函数与行号。'}</Typography.Paragraph><Space wrap><LinkButton to={uploadPath(workspace.id, { intent: 'dump', returnTo: routePaths.overview(workspace.id) })} type="primary">上传 DMP 查看报告</LinkButton><LinkButton to={uploadPath(workspace.id, { intent: 'symbols', returnTo: routePaths.artifacts(workspace.id) })}>上传程序与 PDB</LinkButton><Link to={routePaths.developer(workspace.id)}>使用 CLI 接入</Link></Space></Card> : <div className="metric-grid">{metrics.map(metric => <Link key={metric.key} className="metric-link" to={inbox({ attention: metric.key })}><MetricCard label={metric.label} value={metric.value} hint={metric.hint} icon={metric.icon} tone={metric.tone} /></Link>)}</div>}
    {data.total_occurrences > 0 && <Card title="最近报告" className="section-card" extra={<Link to={inbox()}>查看全部 <ArrowRightOutlined /></Link>}>
      {data.window_occurrences === 0 ? <EmptyState description={data.total_occurrences ? '当前时间范围内没有记录' : '暂无分析数据'} action={data.total_occurrences ? <LinkButton to={routePaths.occurrences(workspace.id)}>查看全部时间的记录</LinkButton> : undefined} /> : <List dataSource={data.recent_occurrences} renderItem={item => <List.Item><OccurrenceCompactSummary occurrence={item} /></List.Item>} />}
    </Card>}
    {data.window_occurrences > 0 && <div className="overview-secondary-grid">
      <Card title="版本分布" extra={<Typography.Text type="secondary">{data.crash_occurrences} 份崩溃报告</Typography.Text>}><List dataSource={data.versions} locale={{ emptyText: '暂无可用崩溃报告' }} renderItem={item => <List.Item extra={<Tag>{item.count}</Tag>}><Link to={inbox({ crash_type: 'crash', ...(item.version === null ? { version_unset: true } : { version: item.version }) })}>{item.version ?? '未声明版本'}</Link></List.Item>} /></Card>
      <Card title="高频崩溃分组" extra={<Link to={routePaths.groups(workspace.id)}>查看分组</Link>}><List dataSource={data.top_groups} locale={{ emptyText: '暂无精确分组，可从崩溃记录继续排查' }} renderItem={group => <List.Item extra={<Tag>{group.occurrence_count}</Tag>}><Link to={routePaths.group(workspace.id, group.id)}>{group.title}</Link></List.Item>} /></Card>
    </div>}
    <div className="report-footnote">{data.total_occurrences === 0 ? '暂无分析数据' : <>平均分析耗时 {data.average_analysis_duration_ms == null ? '—' : `${(data.average_analysis_duration_ms / 1000).toFixed(1)} 秒`} · Hang {data.hang_captures} · 未知类型 {data.unknown_captures} · 拒收 DMP {data.rejected_uploads}</>}</div>
  </div>
}
