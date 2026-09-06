import { LinkButton } from '../components/LinkButton'
import { AppstoreOutlined,CloudUploadOutlined,CodeOutlined,InboxOutlined,MenuOutlined,ToolOutlined } from '@ant-design/icons'
import { Breadcrumb,Button,Layout,Menu,Select,Space,Tabs,Typography } from 'antd'
import { createContext,useContext,useEffect,useRef,useState,type ReactNode } from 'react'
import { Link,NavLink,Outlet,useLocation,useNavigate,useParams } from 'react-router-dom'
import { CrashCapApiError } from '../api/client'
import { useWorkspace,useWorkspaces } from '../api/hooks'
import { ErrorBoundary } from '../components/ErrorBoundary'
import { ErrorState,LoadingState } from '../components/ui'
import { NotFoundPage } from '../pages/NotFoundPage'
import { routePaths,uploadPath } from '../routes/routePaths'
import { clearLastWorkspace,rememberWorkspace } from '../routes/workspaceStorage'
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
  const navigate = useNavigate()
  const spaces = useWorkspaces()
  const [collapsed, setCollapsed] = useState(false)
  const [below, setBelow] = useState(false)
  const navButton = useRef<HTMLButtonElement>(null)
  const wasOpen = useRef(false)
  const closeNavigation = () => setCollapsed(true)
  useEffect(() => {
    if (!below) return
    if (collapsed) {
      if (wasOpen.current) navButton.current?.focus()
      wasOpen.current = false
      return
    }
    wasOpen.current = true
    const frame = requestAnimationFrame(() => document.querySelector<HTMLElement>('.app-sider a')?.focus())
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setCollapsed(true) }
    window.addEventListener('keydown', escape)
    return () => { cancelAnimationFrame(frame); window.removeEventListener('keydown', escape) }
  }, [below, collapsed])
  useEffect(() => { if (window.matchMedia('(max-width: 991px)').matches) setCollapsed(true) }, [location.pathname])
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
    item('overview', <AppstoreOutlined />, '概览', routePaths.overview(workspace.id)),
    item('crashes', <InboxOutlined />, '崩溃分析', routePaths.occurrences(workspace.id)),
    item('symbols', <CodeOutlined />, '符号中心', routePaths.symbols(workspace.id)),
  ]
  const marker = location.pathname.split('/')[3] ?? 'overview'
  const sectionTabs = selected === 'crashes' ? [
    { key: 'occurrences', label: '崩溃记录', path: routePaths.occurrences(workspace.id) },
    { key: 'groups', label: '相同崩溃分组', path: routePaths.groups(workspace.id) },
  ] : selected === 'symbols' ? [
    { key: 'symbols', label: '符号问题', path: routePaths.symbols(workspace.id) },
    { key: 'artifacts', label: '文件库', path: routePaths.artifacts(workspace.id) },
  ] : []

  return (
    <WorkspaceRouteContext.Provider value={workspace}>
      <Layout className="app-layout">
        {!collapsed && <button className="sidebar-backdrop" aria-label="关闭导航" onClick={closeNavigation} />}
        <Sider id="workspace-navigation" aria-label="Workspace 导航" width={250} breakpoint="lg" collapsedWidth="0" collapsed={collapsed} onCollapse={setCollapsed} onBreakpoint={setBelow} trigger={null} className="app-sider">
          <Link to={routePaths.home} className="brand" aria-label="Crash-Cap 平台主页"><div className="brand-mark">C</div><div><div className="brand-name">CRASH-CAP</div><div className="brand-subtitle">Crash intelligence</div></div></Link>
          <div className="sider-workspace"><div className="workspace-switcher"><Typography.Text>当前 Workspace</Typography.Text><Select aria-label="切换 Workspace" value={workspace.id} onChange={id => navigate(routePaths.overview(id))} options={(spaces.data ?? [workspace]).map(space => ({ value: space.id, label: space.display_name ?? space.name }))} /><Link to={routePaths.workspaces}>查看全部空间</Link></div></div>
          <Menu theme="dark" mode="inline" selectedKeys={[selected]} items={menuItems} className="side-menu" />
          <div className="sider-bottom"><Link to={routePaths.developer(workspace.id)}><ToolOutlined /> 接入指南</Link><Typography.Text type="secondary">Crash-Cap · 内网工作台</Typography.Text></div>
        </Sider>
        <Layout inert={below && !collapsed ? true : undefined}>
          <Header className="app-header">
            <Button ref={navButton} className="mobile-nav-button" aria-label="打开导航" aria-expanded={!collapsed} aria-controls="workspace-navigation" icon={<MenuOutlined />} onClick={() => setCollapsed(false)} />
            <Breadcrumb items={[
              { title: <Link to={routePaths.home}>Crash-Cap</Link> },
              { title: <Link to={routePaths.overview(workspace.id)}>{workspaceLabel}</Link> },
              { title: breadcrumbLabel(marker) },
            ]} />
            <Space>{marker === 'upload' ? <Button type="primary" disabled icon={<CloudUploadOutlined />}>上传文件</Button> : <LinkButton to={uploadPath(workspace.id, { returnTo: location.pathname + location.search })} type="primary" icon={<CloudUploadOutlined />}>上传文件</LinkButton>}</Space>
          </Header>
          <Content className="app-content" id="main-content">
            {sectionTabs.length > 0 && <Tabs className="section-tabs" activeKey={marker} onChange={key => navigate(sectionTabs.find(tab => tab.key === key)!.path)} items={sectionTabs.map(({ key, label }) => ({ key, label }))} />}
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
  if (marker === 'groups' || marker === 'occurrences') return 'crashes'
  if (marker === 'symbols' || marker === 'artifacts') return 'symbols'
  return marker || 'overview'
}

function breadcrumbLabel(section: string): string {
  return ({ overview: '概览', occurrences: '崩溃分析', upload: '上传文件', artifacts: '文件库', symbols: '符号问题', groups: '相同崩溃分组', developer: '接入指南' } as Record<string, string>)[section] ?? '页面'
}

function errorDescription(prefix: string, error: unknown) {
  if (!(error instanceof CrashCapApiError)) return prefix
  return <span>{prefix}（{error.code ?? error.status}）{error.requestId ? <><br />Request ID: <Typography.Text code>{error.requestId}</Typography.Text></> : null}</span>
}
