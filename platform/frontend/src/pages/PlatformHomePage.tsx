import { useEffect, useState } from 'react'
import { Alert, Button, Card, List, Modal, Space, Tag, Typography } from 'antd'
import { CloudUploadOutlined, InboxOutlined, PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { usePlatformOverview } from '../api/hooks'
import { OccurrenceCompactSummary } from '../components/OccurrenceSummary'
import { EmptyState, ErrorState, LoadingState, MetricCard, PageTitle } from '../components/ui'
import { routePaths } from '../routes/routePaths'
import { clearLastWorkspace, migrateLegacyWorkspaceStorage } from '../routes/workspaceStorage'

const { Text } = Typography

export function PlatformHomePage() {
  const overview = usePlatformOverview()
  const [uploadOpen, setUploadOpen] = useState(false)
  const [lastWorkspaceId, setLastWorkspaceId] = useState<string | null>(() => migrateLegacyWorkspaceStorage())

  useEffect(() => {
    if (!overview.data || !lastWorkspaceId) return
    if (!overview.data.workspaces.some((item) => item.workspace.id === lastWorkspaceId)) {
      clearLastWorkspace(lastWorkspaceId)
      setLastWorkspaceId(null)
    }
  }, [lastWorkspaceId, overview.data])

  if (overview.isLoading) return <div className="platform-page"><LoadingState rows={10} title /></div>
  if (overview.isError || !overview.data) return <div className="platform-page"><PageTitle kicker="CRASH-CAP / PRIVATE INTRANET" title="Crash-Cap" /><ErrorState description="平台概览加载失败" onRetry={() => void overview.refetch()} /></div>

  const data = overview.data
  const lastWorkspace = lastWorkspaceId ? data.workspaces.find((item) => item.workspace.id === lastWorkspaceId)?.workspace : undefined
  return <div className="platform-page">
    <PageTitle kicker="CRASH-CAP / PRIVATE INTRANET" title="Crash-Cap" description="稳定的平台入口 · 崩溃事故发现、分析与符号健康工作台" extra={<Space><Link to={routePaths.workspaces}><Button icon={<PlusOutlined />}>管理 Workspace</Button></Link><Button type="primary" icon={<CloudUploadOutlined />} onClick={() => setUploadOpen(true)} disabled={!data.workspace_count}>上传 Dump</Button></Space>} />
    <Card className="trust-banner" variant="borderless"><SafetyCertificateOutlined /><span><strong>匿名可信内网</strong>　无登录、RBAC 或 Workspace 权限过滤；请只部署在受信任内网或 VPN。</span><Tag color="blue">RAW 下载默认关闭</Tag></Card>
    {lastWorkspace && <Alert className="page-alert" type="info" showIcon message="继续上次 Workspace" description={<Link to={routePaths.overview(lastWorkspace.id)}>{lastWorkspace.display_name ?? lastWorkspace.name} · 打开 Workspace 概览</Link>} />}
    <div className="metric-grid metric-grid-4">
      <MetricCard label="分析中" value={data.attention.in_progress} hint="由 latest attempt 非终态判定" tone="blue" />
      <MetricCard label="最近尝试失败" value={data.attention.latest_attempt_failed} hint="不覆盖仍可用的 Current" tone="red" />
      <MetricCard label="Unclassified Crash" value={data.attention.unclassified_crashes} hint="仅统计 Current crash" tone="orange" />
      <MetricCard label="符号受影响" value={data.attention.symbol_affected_occurrences} hint="缺失或不匹配符号" tone="orange" />
    </div>
    <Card title={`Workspaces · ${data.workspace_count}`} className="section-card">
      {!data.workspaces.length ? <EmptyState description="还没有 Workspace" action={<Link to={routePaths.workspaces}><Button type="primary">创建第一个 Workspace</Button></Link>} /> : <div className="workspace-grid">
        {data.workspaces.map((item) => <Link key={item.workspace.id} to={routePaths.overview(item.workspace.id)} className="workspace-card-link"><Card className="workspace-card" hoverable><div className="workspace-card-top"><div className="workspace-glyph">{(item.workspace.display_name ?? item.workspace.name).slice(0, 1).toUpperCase()}</div><Tag color={item.attention_count ? 'orange' : 'green'}>{item.attention_count} 待关注</Tag></div><Typography.Title level={3}>{item.workspace.display_name ?? item.workspace.name}</Typography.Title><Text type="secondary">最近 7 天 {item.occurrence_count} Occurrence</Text><div className="workspace-card-footer"><Text type="secondary">{item.last_occurrence_at ? `最后发生 ${new Date(item.last_occurrence_at).toLocaleString('zh-CN')}` : '尚无 Occurrence'}</Text><InboxOutlined /></div></Card></Link>)}
      </div>}
    </Card>
    <Card title="最近 Occurrence" extra={<Text type="secondary">最多 10 条 · 与 Crash Inbox 使用同一状态口径</Text>} className="section-card">
      <List dataSource={data.recent_occurrences} locale={{ emptyText: '最近 7 天没有 Occurrence' }} renderItem={(occurrence) => <List.Item><OccurrenceCompactSummary occurrence={occurrence} /></List.Item>} />
    </Card>
    <Modal title="选择上传目标 Workspace" open={uploadOpen} footer={null} onCancel={() => setUploadOpen(false)}><List dataSource={data.workspaces} locale={{ emptyText: '请先创建 Workspace' }} renderItem={(item) => <List.Item actions={[<Link to={routePaths.upload(item.workspace.id)}><Button type="primary" icon={<CloudUploadOutlined />}>选择并上传</Button></Link>]}><List.Item.Meta title={item.workspace.display_name ?? item.workspace.name} description={item.workspace.name} /></List.Item>} /></Modal>
  </div>
}
