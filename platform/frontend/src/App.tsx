import { useMemo, useState } from 'react'
import { Avatar, Breadcrumb, Button, ConfigProvider, Layout, Menu, Space, Tag, Tooltip, Typography } from 'antd'
import { AppstoreOutlined, BarChartOutlined, CodeOutlined, ExportOutlined, PartitionOutlined, SafetyCertificateOutlined, SlidersOutlined } from '@ant-design/icons'
import type { Workspace } from './types'
import { WorkspaceList } from './components/WorkspaceList'
import { WorkspaceOverviewPage } from './pages/WorkspaceOverviewPage'
import { BuildPage } from './pages/BuildPage'
import { SymbolHealthPage } from './pages/SymbolHealthPage'
import { GroupPage } from './pages/GroupPage'
import { OccurrenceReport } from './pages/OccurrenceReport'

const { Header, Sider, Content } = Layout
type Section = 'overview' | 'builds' | 'symbols' | 'groups'
type Page = { type: 'section'; section: Section; buildId?: string } | { type: 'occurrence'; occurrenceId: string } | { type: 'group'; groupId?: string }

function WorkspaceShell({ workspace, onSwitch }: { workspace: Workspace; onSwitch: () => void }) {
  const [page, setPage] = useState<Page>({ type: 'section', section: 'overview' })
  const section = page.type === 'section' ? page.section : page.type === 'group' ? 'groups' : 'overview'
  const menuItems = [
    { key: 'overview', icon: <AppstoreOutlined />, label: 'Workspace 概览' },
    { key: 'builds', icon: <CodeOutlined />, label: 'Build 与符号' },
    { key: 'symbols', icon: <BarChartOutlined />, label: 'Symbol Health' },
    { key: 'groups', icon: <PartitionOutlined />, label: 'Exact Groups' },
  ]
  const body = page.type === 'occurrence' ? <OccurrenceReport workspace={workspace} occurrenceId={page.occurrenceId} onBack={() => setPage({ type: 'section', section: 'overview' })} onOpenGroup={(groupId) => setPage({ type: 'group', groupId })} /> : page.type === 'group' ? <GroupPage workspace={workspace} initialGroupId={page.groupId} onOpenOccurrence={(occurrenceId) => setPage({ type: 'occurrence', occurrenceId })} /> : page.section === 'overview' ? <WorkspaceOverviewPage workspace={workspace} onOpenOccurrence={(occurrenceId) => setPage({ type: 'occurrence', occurrenceId })} onOpenGroup={(groupId) => setPage({ type: 'group', groupId })} onOpenBuild={(buildId) => setPage({ type: 'section', section: 'builds', buildId })} /> : page.section === 'builds' ? <BuildPage workspace={workspace} initialBuildId={page.buildId} onOpenOccurrence={(occurrenceId) => setPage({ type: 'occurrence', occurrenceId })} /> : page.section === 'symbols' ? <SymbolHealthPage workspace={workspace} onOpenOccurrence={(occurrenceId) => setPage({ type: 'occurrence', occurrenceId })} onOpenBuild={(buildId) => setPage({ type: 'section', section: 'builds', buildId })} /> : <GroupPage workspace={workspace} onOpenOccurrence={(occurrenceId) => setPage({ type: 'occurrence', occurrenceId })} />

  return <Layout className="app-layout">
    <Sider width={250} breakpoint="lg" collapsedWidth="0" className="app-sider">
      <div className="brand"><div className="brand-mark">C</div><div><div className="brand-name">CRASH-CAP</div><div className="brand-subtitle">Crash intelligence</div></div></div>
      <div className="sider-workspace"><Avatar size={34} className="workspace-avatar">{workspace.display_name.slice(0, 1).toUpperCase()}</Avatar><div className="sider-workspace-copy"><Typography.Text strong>{workspace.display_name}</Typography.Text><Typography.Text type="secondary">{workspace.name}</Typography.Text></div></div>
      <Menu mode="inline" selectedKeys={[section]} items={menuItems} onClick={({ key }) => setPage({ type: 'section', section: key as Section })} className="side-menu" />
      <div className="sider-bottom"><Tag color="green"><span className="status-dot" /> internal</Tag><Typography.Text type="secondary">API /api/v1</Typography.Text><Button type="text" icon={<ExportOutlined />} onClick={onSwitch}>切换 Workspace</Button></div>
    </Sider>
    <Layout>
      <Header className="app-header"><Breadcrumb items={[{ title: 'Crash-Cap' }, { title: workspace.display_name }, ...(page.type === 'occurrence' ? [{ title: 'Occurrence Report' }] : page.type === 'group' ? [{ title: 'Exact Group' }] : [{ title: menuItems.find((item) => item.key === page.section)?.label }])]} /><Space><Tooltip title="无登录 / 无权限过滤"><SafetyCertificateOutlined className="header-icon" /></Tooltip><Tag color="blue">Phase 2</Tag><Button type="text" icon={<SlidersOutlined />} onClick={onSwitch}>Workspaces</Button></Space></Header>
      <Content className="app-content">{body}</Content>
    </Layout>
  </Layout>
}

export function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(() => {
    try { const stored = localStorage.getItem('crash-cap.workspace'); return stored ? JSON.parse(stored) as Workspace : null } catch { return null }
  })
  const selectWorkspace = (next: Workspace) => { setWorkspace(next); localStorage.setItem('crash-cap.workspace', JSON.stringify(next)) }
  const theme = useMemo(() => ({ token: { colorPrimary: '#4e8cff', colorInfo: '#4e8cff', colorSuccess: '#39c79a', colorWarning: '#f6ad55', colorError: '#ff6b7a', borderRadius: 10, fontFamily: 'Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' }, components: { Layout: { headerBg: '#ffffff', siderBg: '#101a35', bodyBg: '#f5f7fb' }, Menu: { darkItemBg: '#101a35', darkSubMenuItemBg: '#101a35', darkItemSelectedBg: '#1b2b54', darkItemHoverBg: '#172447', darkItemColor: '#a9b6d2', darkItemSelectedColor: '#ffffff' }, Card: { headerFontSize: 15 } } }), [])
  return <ConfigProvider theme={theme}><div className="app-root">{workspace ? <WorkspaceShell workspace={workspace} onSwitch={() => setWorkspace(null)} /> : <WorkspaceList onSelect={selectWorkspace} />}</div></ConfigProvider>
}
