import { AppstoreOutlined,BarChartOutlined,CloudUploadOutlined,CodeOutlined,ExportOutlined,InboxOutlined,PartitionOutlined,SafetyCertificateOutlined,ToolOutlined } from '@ant-design/icons'
import { Avatar,Breadcrumb,Button,Layout,Menu,Space,Tag,Tooltip,Typography } from 'antd'
import { createContext,useContext,useEffect,type ReactNode } from 'react'
import { Link,NavLink,Outlet,useLocation,useParams } from 'react-router-dom'
import { CrashCapApiError } from '../api/client'
import { useWorkspace } from '../api/hooks'
import { ErrorBoundary } from '../components/ErrorBoundary'
import { ErrorState,LoadingState } from '../components/ui'
import { NotFoundPage } from '../pages/NotFoundPage'
import { routePaths } from '../routes/routePaths'
import { clearLastWorkspace,rememberWorkspace } from '../routes/workspaceStorage'
import { semantic } from '../theme/tokens'
import type { Workspace } from '../types'

const { Header, Sider, Content } = Layout
const WorkspaceRouteContext = createContext<Workspace | null>(null)

export function useWorkspaceRoute(): Workspace {
  const workspace = useContext(WorkspaceRouteContext)
  if (!workspace) throw new Error('useWorkspaceRoute must be used inside WorkspaceLayout')
  return workspace
}

export function WorkspaceLayout() {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const location = useLocation()
  const query = useWorkspace(workspaceId)

  useEffect(() => {
    if (query.data) rememberWorkspace(query.data.id)
    if (workspaceId && query.error instanceof CrashCapApiError && query.error.status === 404) {
      clearLastWorkspace(workspaceId)
    }
  }, [query.data, query.error, workspaceId])

  if (!workspaceId) return <NotFoundPage title="Workspace 路由缺少 ID" />
  if (query.isLoading) return <div className="workspace-route-state"><LoadingState rows={8} title /></div>
  if (query.error instanceof CrashCapApiError && query.error.status === 404) {
    return <NotFoundPage title="Workspace 不存在" description={`服务端未找到 ${workspaceId}；已清除失效的继续入口。`} showWorkspaceLink={false} />
  }
  if (query.isError || !query.data) {
    return <div className="workspace-route-state"><ErrorState description={errorDescription('Workspace 加载失败', query.error)} onRetry={() => void query.refetch()} /></div>
  }

  const workspace = query.data
  const workspaceLabel = workspace.display_name ?? workspace.name
  const selected = selectedSection(location.pathname)
  const menuItems = [
    item('overview', <AppstoreOutlined />, 'Workspace 概览', routePaths.overview(workspace.id)),
    item('occurrences', <InboxOutlined />, 'Crash Inbox', routePaths.occurrences(workspace.id)),
    item('upload', <CloudUploadOutlined />, '上传文件', routePaths.upload(workspace.id)),
    item('artifacts', <CodeOutlined />, '产物与符号', routePaths.artifacts(workspace.id)),
    item('symbols', <BarChartOutlined />, 'Symbol Health', routePaths.symbols(workspace.id)),
    item('groups', <PartitionOutlined />, 'Exact Groups', routePaths.groups(workspace.id)),
    item('developer', <ToolOutlined />, 'CLI 上传', routePaths.developer(workspace.id)),
  ]

  return (
    <WorkspaceRouteContext.Provider value={workspace}>
      <Layout className="app-layout">
        <Sider width={250} breakpoint="lg" collapsedWidth="0" className="app-sider">
          <Link to={routePaths.home} className="brand" aria-label="Crash-Cap 平台主页"><div className="brand-mark">C</div><div><div className="brand-name">CRASH-CAP</div><div className="brand-subtitle">Crash intelligence</div></div></Link>
          <div className="sider-workspace"><Avatar size={34} style={{ background: semantic.navAvatarBg, color: semantic.navAvatarText }}>{workspaceLabel.slice(0, 1).toUpperCase()}</Avatar><div className="sider-workspace-copy"><Typography.Text strong>{workspaceLabel}</Typography.Text><Typography.Text type="secondary">{workspace.name}</Typography.Text></div></div>
          <Menu theme="dark" mode="inline" selectedKeys={[selected]} items={menuItems} className="side-menu" />
          <div className="sider-bottom"><Tag color="green"><span className="status-dot" /> internal</Tag><Typography.Text type="secondary">API /api/v3</Typography.Text><Link to={routePaths.workspaces}><Button type="text" icon={<ExportOutlined />}>切换 Workspace</Button></Link></div>
        </Sider>
        <Layout>
          <Header className="app-header">
            <Breadcrumb items={[
              { title: <Link to={routePaths.home}>Crash-Cap</Link> },
              { title: <Link to={routePaths.overview(workspace.id)}>{workspaceLabel}</Link> },
              { title: breadcrumbLabel(selected) },
            ]} />
            <Space><Tooltip title="无登录 / 无权限过滤"><SafetyCertificateOutlined className="header-icon" /></Tooltip><Link to={routePaths.workspaces}><Button type="text">Workspaces</Button></Link></Space>
          </Header>
          <Content className="app-content" id="main-content">
            <ErrorBoundary key={location.pathname}><Outlet /></ErrorBoundary>
          </Content>
        </Layout>
      </Layout>
    </WorkspaceRouteContext.Provider>
  )
}

function item(key: string, icon: ReactNode, label: string, to: string) {
  return { key, icon, label: <NavLink to={to}>{label}</NavLink> }
}

function selectedSection(pathname: string): string {
  const marker = pathname.split('/').filter(Boolean)[2]
  return marker || 'overview'
}

function breadcrumbLabel(section: string): string {
  return ({ overview: 'Workspace 概览', occurrences: 'Crash Inbox', upload: '上传文件', artifacts: '产物与符号', symbols: 'Symbol Health', groups: 'Exact Groups', developer: '开发者接入' } as Record<string, string>)[section] ?? '页面'
}

function errorDescription(prefix: string, error: unknown) {
  if (!(error instanceof CrashCapApiError)) return prefix
  return <span>{prefix}（{error.code ?? error.status}）{error.requestId ? <><br />Request ID: <Typography.Text code>{error.requestId}</Typography.Text></> : null}</span>
}
