import { LinkButton } from '../components/LinkButton'
import { CloudUploadOutlined } from '@ant-design/icons'
import { Alert,Button,Card,Collapse,List,Space,Tag,Typography } from 'antd'
import { useEffect,useState } from 'react'
import { Link } from 'react-router-dom'
import { usePlatformOverview } from '../api/hooks'
import { OccurrenceCompactSummary } from '../components/OccurrenceSummary'
import { EmptyState,ErrorState,LoadingState,PageTitle } from '../components/ui'
import { routePaths } from '../routes/routePaths'
import { clearLastWorkspace,getRecentWorkspaceIds,migrateLegacyWorkspaceStorage } from '../routes/workspaceStorage'

export function PlatformHomePage() {
  const overview = usePlatformOverview()
  const [lastWorkspaceId, setLastWorkspaceId] = useState(() => migrateLegacyWorkspaceStorage())
  useEffect(() => {
    if (overview.data && lastWorkspaceId && !overview.data.workspaces.some(item => item.workspace.id === lastWorkspaceId)) {
      clearLastWorkspace(lastWorkspaceId); setLastWorkspaceId(null)
    }
  }, [lastWorkspaceId, overview.data])
  if (overview.isLoading) return <div className="platform-page"><LoadingState rows={6} title /></div>
  if (overview.isError || !overview.data) return <div className="platform-page"><PageTitle kicker="CRASH-CAP" title="Crash-Cap" /><ErrorState description="平台概览加载失败" onRetry={() => void overview.refetch()} /></div>
  const data = overview.data
  const last = data.workspaces.find(item => item.workspace.id === lastWorkspaceId)?.workspace
  const recentIds = getRecentWorkspaceIds()
  const spaces = [...data.workspaces].sort((a, b) => {
    const rank = (id: string) => recentIds.includes(id) ? recentIds.indexOf(id) : recentIds.length
    return rank(a.workspace.id) - rank(b.workspace.id)
  }).slice(0, 4)
  return <div className="platform-page">
    <PageTitle kicker="CRASH ANALYSIS" title="Crash-Cap" description="查看崩溃，补齐符号，回到问题本身。" extra={<Space wrap><LinkButton to={routePaths.platformArtifacts}>公共文件库</LinkButton><LinkButton to={routePaths.platformUpload} type="primary" icon={<CloudUploadOutlined />}>上传文件</LinkButton></Space>} />
    {last && <Alert className="page-alert" type="info" showIcon message="继续上次 Workspace" description={<Link to={routePaths.overview(last.id)}>{last.display_name ?? last.name} · 查看待处理事项</Link>} />}
    <Card title="工作空间" extra={<Link to={routePaths.workspaces}>查看全部 {data.workspace_count} 个空间</Link>} className="section-card">
      {!spaces.length ? <EmptyState description="还没有 Workspace" action={<LinkButton to={routePaths.workspaces} type="primary">创建第一个 Workspace</LinkButton>} /> : <div className="workspace-grid">{spaces.map(item => <Link key={item.workspace.id} to={routePaths.overview(item.workspace.id)} className="workspace-card-link"><Card className="workspace-card" hoverable><Space><Tag>{item.attention_count} 待关注</Tag>{recentIds.includes(item.workspace.id) && <Typography.Text type="secondary">最近使用</Typography.Text>}</Space><Typography.Title level={3}>{item.workspace.display_name ?? item.workspace.name}</Typography.Title><Typography.Text type="secondary">最近 7 天 · {item.occurrence_count} 份崩溃记录</Typography.Text><div className="workspace-card-footer"><Typography.Text type="secondary">{item.last_occurrence_at ? `最近发生 ${new Date(item.last_occurrence_at).toLocaleString()}` : '尚未上传 DMP'}</Typography.Text></div></Card></Link>)}</div>}
    </Card>
    <Card title="最近报告" className="section-card"><List dataSource={data.recent_occurrences} locale={{ emptyText: '最近 7 天没有报告' }} renderItem={occurrence => <List.Item><OccurrenceCompactSummary occurrence={occurrence} /></List.Item>} /></Card>
    <Collapse ghost items={[{ key: 'deployment', label: '部署信息', children: <Typography.Paragraph type="secondary">当前为匿名内网模式，无登录与 Workspace 权限过滤。请在受信任内网或 VPN 使用；原始文件下载由部署配置控制。</Typography.Paragraph> }]} />
  </div>
}
