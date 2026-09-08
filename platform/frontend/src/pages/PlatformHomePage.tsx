import { ArrowRightOutlined, ClockCircleOutlined, FolderOpenOutlined, PlusOutlined } from '@ant-design/icons'
import { Card, List, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { usePlatformOverview } from '../api/hooks'
import { LinkButton } from '../components/LinkButton'
import { OccurrenceCompactSummary } from '../components/OccurrenceSummary'
import { ErrorState, LoadingState, PageTitle } from '../components/ui'
import { routePaths } from '../routes/routePaths'
import { clearLastWorkspace, getRecentWorkspaceIds, migrateLegacyWorkspaceStorage } from '../routes/workspaceStorage'

export function PlatformHomePage() {
  const overview = usePlatformOverview()
  const [lastWorkspaceId, setLastWorkspaceId] = useState(() => migrateLegacyWorkspaceStorage())
  useEffect(() => {
    if (overview.data && lastWorkspaceId && !overview.data.workspaces.some(item => item.workspace.id === lastWorkspaceId)) {
      clearLastWorkspace(lastWorkspaceId); setLastWorkspaceId(null)
    }
  }, [lastWorkspaceId, overview.data])
  if (overview.isLoading) return <div className="platform-page"><LoadingState rows={6} title /></div>
  if (overview.isError || !overview.data) return <div className="platform-page"><PageTitle title="平台概览" /><ErrorState description="平台概览加载失败" onRetry={() => void overview.refetch()} /></div>
  const data = overview.data
  const last = data.workspaces.find(item => item.workspace.id === lastWorkspaceId)?.workspace
  const recentIds = getRecentWorkspaceIds()
  const spaces = [...data.workspaces].sort((a, b) => {
    const rank = (id: string) => recentIds.includes(id) ? recentIds.indexOf(id) : recentIds.length
    return rank(a.workspace.id) - rank(b.workspace.id)
  }).slice(0, 4)
  return <div className="platform-page platform-home">
    <PageTitle title="平台概览" description="从工作空间开始，查看崩溃、补齐符号，跟进每一次分析。" />
    {last && <Link className="continue-workspace" to={routePaths.overview(last.id)}>
      <ClockCircleOutlined /><span>继续上次工作空间</span><strong>{last.display_name ?? last.name}</strong><ArrowRightOutlined />
    </Link>}
    {!spaces.length ? <section className="first-workspace-panel" aria-labelledby="first-workspace-title">
      <span className="first-workspace-icon"><FolderOpenOutlined /></span>
      <Typography.Title level={2} id="first-workspace-title">从第一个工作空间开始</Typography.Title>
      <Typography.Paragraph type="secondary">将项目的崩溃记录与符号文件归集到一起。创建空间后，即可上传文件并查看分析结果。</Typography.Paragraph>
      <LinkButton to={routePaths.workspaces} type="primary" icon={<PlusOutlined />}>创建工作空间</LinkButton>
      <span className="first-workspace-note">工作空间帮助团队按项目组织分析资料</span>
    </section> : <>
      <section className="home-workspaces" aria-labelledby="home-workspaces-title">
        <div className="section-heading"><div><h2 id="home-workspaces-title">工作空间</h2><span>{data.workspace_count} 个空间 · 最近使用优先</span></div><Link to={routePaths.workspaces}>查看全部 <ArrowRightOutlined /></Link></div>
        <div className="workspace-grid">{spaces.map(item => <Link key={item.workspace.id} to={routePaths.overview(item.workspace.id)} className="workspace-card-link"><Card className="workspace-card" hoverable>
          <div className="workspace-card-top"><span className="workspace-glyph"><FolderOpenOutlined /></span>{item.attention_count > 0 && <Tag color="gold">{item.attention_count} 待关注</Tag>}</div>
          <Typography.Title level={3} title={item.workspace.display_name ?? item.workspace.name}>{item.workspace.display_name ?? item.workspace.name}</Typography.Title>
          <Typography.Text type="secondary">最近 7 天 · {item.occurrence_count} 份崩溃记录</Typography.Text>
          <div className="workspace-card-footer"><Space size={4}><ClockCircleOutlined /><Typography.Text type="secondary">{recentIds.includes(item.workspace.id) ? '最近使用' : item.last_occurrence_at ? new Date(item.last_occurrence_at).toLocaleDateString('zh-CN') : '尚无崩溃记录'}</Typography.Text></Space><ArrowRightOutlined /></div>
        </Card></Link>)}</div>
      </section>
      <section className="home-reports" aria-labelledby="home-reports-title">
        <div className="section-heading"><div><h2 id="home-reports-title">最近报告</h2><span>最近 7 天的崩溃分析</span></div></div>
        <Card className="recent-reports-card"><List dataSource={data.recent_occurrences} locale={{ emptyText: '最近 7 天没有报告，上传 DMP 后将在这里展示。' }} renderItem={occurrence => <List.Item>
          <OccurrenceCompactSummary occurrence={occurrence} workspaceName={data.workspaces.find(item => item.workspace.id === occurrence.workspace_id)?.workspace.display_name ?? data.workspaces.find(item => item.workspace.id === occurrence.workspace_id)?.workspace.name} />
        </List.Item>} /></Card>
      </section>
    </>}
  </div>
}
