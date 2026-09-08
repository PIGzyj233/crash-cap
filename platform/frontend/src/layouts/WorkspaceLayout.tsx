import { AppstoreOutlined, CodeOutlined, InboxOutlined, ToolOutlined } from '@ant-design/icons'
import { Breadcrumb, Menu, Select, Tabs, Typography } from 'antd'
import { createContext, useContext, useEffect, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { CrashCapApiError } from '../api/client'
import { useWorkspace, useWorkspaces } from '../api/hooks'
import { ErrorBoundary } from '../components/ErrorBoundary'
import { ErrorState, LoadingState } from '../components/ui'
import { NotFoundPage } from '../pages/NotFoundPage'
import { routePaths } from '../routes/routePaths'
import { clearLastWorkspace, rememberWorkspace } from '../routes/workspaceStorage'
import type { Workspace } from '../types'
import { ApplicationShell } from './ApplicationShell'

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
  const query = useWorkspace(workspaceId)
  useEffect(() => {
    if (query.data) rememberWorkspace(query.data.id)
    if (workspaceId && query.error instanceof CrashCapApiError && query.error.status === 404) clearLastWorkspace(workspaceId)
  }, [query.data, query.error, workspaceId])

  const frame = (content: ReactNode, sidebar?: ReactNode) => <WorkspaceRouteContext.Provider value={query.data ?? null}><ApplicationShell sidebar={sidebar}>{content}</ApplicationShell></WorkspaceRouteContext.Provider>

  if (!workspaceId) return frame(<NotFoundPage title="Workspace 路由缺少 ID" />)
  if (query.isLoading) return frame(<div className="workspace-route-state"><LoadingState rows={8} title /></div>)
  if (query.error instanceof CrashCapApiError && query.error.status === 404) return frame(<NotFoundPage title="Workspace 不存在" description={`服务端未找到 ${workspaceId}；已清除失效的继续入口。`} showWorkspaceLink={false} />)
  if (query.isError || !query.data) return frame(<div className="workspace-route-state"><ErrorState description={errorDescription('Workspace 加载失败', query.error)} onRetry={() => void query.refetch()} /></div>)

  const workspace = query.data
  const label = workspace.display_name ?? workspace.name
  const marker = location.pathname.split('/')[3] ?? 'overview'
  const selected = selectedSection(marker)
  const menuItems = [
    item('overview', <AppstoreOutlined />, '概览', routePaths.overview(workspace.id)),
    item('crashes', <InboxOutlined />, '崩溃分析', routePaths.occurrences(workspace.id)),
    item('symbols', <CodeOutlined />, '符号中心', routePaths.symbols(workspace.id)),
  ]
  const tabs = selected === 'crashes' ? [
    { key: 'occurrences', label: '崩溃记录', path: routePaths.occurrences(workspace.id) },
    { key: 'groups', label: '相同崩溃分组', path: routePaths.groups(workspace.id) },
  ] : selected === 'symbols' ? [
    { key: 'symbols', label: '符号问题', path: routePaths.symbols(workspace.id) },
    { key: 'artifacts', label: '文件库', path: routePaths.artifacts(workspace.id) },
  ] : []
  const sidebar = <>
    <div className="workspace-switcher">
      <span className="navigation-section-label">工作空间</span>
      <Select aria-label="切换工作空间" title={label} value={workspace.id} onChange={id => navigate(routePaths.overview(id))}
        options={(spaces.data ?? [workspace]).map(space => ({ value: space.id, label: space.display_name ?? space.name, title: space.display_name ?? space.name }))} />
      <Link className="workspace-directory-link" to={routePaths.workspaces}>查看全部空间</Link>
    </div>
    <nav className="workspace-task-navigation" aria-label="工作空间任务"><Menu mode="inline" selectedKeys={[selected]} items={menuItems} /></nav>
    <div className="workspace-navigation-footer"><NavLink to={routePaths.developer(workspace.id)}><ToolOutlined /> 接入指南</NavLink><span>Crash-Cap · 崩溃分析平台</span></div>
  </>
  return frame(
    <div className="workspace-content">
      <Breadcrumb className="workspace-breadcrumb" items={[
        { title: <Link to={routePaths.workspaces}>工作空间</Link> },
        { title: <Link to={routePaths.overview(workspace.id)} title={label}>{label}</Link> },
        { title: breadcrumbLabel(marker) },
      ]} />
      {tabs.length > 0 && <Tabs className="section-tabs" activeKey={marker} onChange={key => navigate(tabs.find(tab => tab.key === key)!.path)} items={tabs.map(({ key, label }) => ({ key, label }))} />}
      <ErrorBoundary key={location.pathname}><Outlet /></ErrorBoundary>
    </div>
  , sidebar)
}

function item(key: string, icon: ReactNode, label: string, to: string) { return { key, icon, label: <NavLink to={to}>{label}</NavLink> } }
function selectedSection(marker: string) {
  if (marker === 'groups' || marker === 'occurrences') return 'crashes'
  if (marker === 'symbols' || marker === 'artifacts') return 'symbols'
  return marker
}
function breadcrumbLabel(section: string): string {
  return ({ overview: '概览', occurrences: '崩溃分析', upload: '上传文件', artifacts: '文件库', symbols: '符号问题', groups: '相同崩溃分组', developer: '接入指南' } as Record<string, string>)[section] ?? '页面'
}
function errorDescription(prefix: string, error: unknown) {
  if (!(error instanceof CrashCapApiError)) return prefix
  return <span>{prefix}（{error.code ?? error.status}）{error.requestId ? <><br />Request ID: <Typography.Text code>{error.requestId}</Typography.Text></> : null}</span>
}
