import { ArrowRightOutlined,CloudUploadOutlined } from '@ant-design/icons'
import { Alert,Button,Card,Col,Divider,List,Progress,Row,Space,Statistic,Tag,Typography } from 'antd'
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useWorkspaceOverview } from '../api/hooks'
import { DataTable } from '../components/DataTable'
import { ErrorState,HashValue,LoadingState,MetricCard,PageTitle,QualityScore,StatusTag } from '../components/ui'
import { routePaths } from '../routes/routePaths'
import type { Workspace } from '../types'

const { Text } = Typography
const MAX_DUMP_SIZE = 256 * 1024 * 1024

function formatDuration(ms: number) {
  if (ms < 1_000) return `${ms} ms`
  return `${(ms / 1_000).toFixed(1)} s`
}

export function WorkspaceOverviewPage({ workspace, onOpenOccurrence, onOpenGroup }: { workspace: Workspace; onOpenOccurrence: (occurrenceId: string) => void; onOpenGroup: (groupId: string) => void }) {
  void onOpenOccurrence
  void onOpenGroup
  const recentWindow = useMemo(() => {
    const to = new Date()
    const from = new Date(to.getTime() - 7 * 24 * 60 * 60 * 1_000)
    return { from: from.toISOString(), to: to.toISOString() }
  }, [])
  const { data: overview, isLoading, isError, refetch } = useWorkspaceOverview(workspace.id, recentWindow)

  if (isLoading) return <LoadingState rows={6} title />
  if (isError || !overview) return <ErrorState description="概览加载失败" onRetry={() => void refetch()} />

  return (
    <div>
      <PageTitle kicker={`${workspace.display_name} / OVERVIEW`} title="Workspace 概览" description="最近 7 天 · 统计只读取每个 Occurrence 的 Current Analysis" extra={<Space><Tag color="green">匿名内网</Tag><Tag color="geekblue">{workspace.default_architecture}</Tag></Space>} />
      <div className="metric-grid">
        <MetricCard label="Crash Occurrence" value={overview.crash_occurrences} hint="不同 DMP 内容计一次，reprocess 不增加" tone="blue" />
        <MetricCard label="Exact Groups" value={overview.exact_groups} hint="有精确证据才入组" tone="green" />
        <MetricCard label="Unclassified" value={overview.unclassified} hint="证据不足时保持正常路径" tone="orange" />
        <MetricCard label="平均分析耗时" value={formatDuration(overview.average_analysis_duration_ms)} hint={`失败率 ${(overview.failure_rate * 100).toFixed(1)}%`} tone="neutral" />
      </div>
      <Row gutter={[24, 24]}>
        <Col xs={24} lg={14} xl={16}>
          <Card title="按 Version 聚合" extra={<Text type="secondary">读取 DMP 当前版本标签</Text>} className="section-card">
            <DataTable rowKey={(row) => row.version ?? 'unknown'} dataSource={overview.versions} minWidth={520} columns={[{ title: 'Version', dataIndex: 'version', render: (value: string | null) => value ?? <Tag>未声明版本</Tag> }, { title: 'Crash Occurrence', dataIndex: 'count', width: 170, align: 'right', className: 'cc-num', render: (value: number) => <Text strong>{value}</Text> }, { title: '占比', key: 'ratio', width: 160, align: 'right', render: (_, row) => <Progress percent={Math.round((row.count / Math.max(overview.crash_occurrences, 1)) * 100)} showInfo={false} size="small" /> }]} />
          </Card>
          <Card title="Top Exact Groups" className="section-card" extra={<Link to={routePaths.groups(workspace.id)}>查看全部 <ArrowRightOutlined /></Link>}>
            <List dataSource={overview.top_groups} locale={{ emptyText: '还没有 Exact Group' }} renderItem={(group) => <List.Item actions={[<Link to={routePaths.group(workspace.id, group.id)}>查看</Link>]}>
              <List.Item.Meta avatar={<div className="group-index">{group.occurrence_count}</div>} title={<span>{group.title}</span>} description={<Space size={8}><StatusTag status={group.status} /><HashValue value={group.fingerprint} length={18} /></Space>} />
            </List.Item>} />
          </Card>
        </Col>
        <Col xs={24} lg={10} xl={8}>
          <Card title="快捷操作" className="section-card"><Space direction="vertical" style={{ width: '100%' }}><Link to={routePaths.upload(workspace.id)}><Button type="primary" block icon={<CloudUploadOutlined />}>上传文件</Button></Link><Link to={routePaths.occurrences(workspace.id)}><Button block>打开 Crash Inbox</Button></Link></Space></Card>
          <Card title="质量与运行健康" className="section-card">
            <Space direction="vertical" style={{ width: '100%' }} size={16}>
              <QualityScore score={overview.symbol_completeness} />
              <div className="health-row"><span>解析失败率</span><Text strong>{(overview.failure_rate * 100).toFixed(1)}%</Text></div>
              <Divider style={{ margin: '0' }} />
              <div className="separate-metrics"><Statistic title="Hang captures" value={overview.hang_captures} /><Statistic title="Unknown" value={overview.unknown_captures} /><Statistic title="Rejected uploads" value={overview.rejected_uploads} /></div>
              <Alert type="info" showIcon message="Hang / Unknown / Rejected 独立展示，不混入 Crash Occurrence。" />
            </Space>
          </Card>

        </Col>
      </Row>
    </div>
  )
}
