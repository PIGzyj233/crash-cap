import { CloudUploadOutlined, DownOutlined, MenuOutlined, SettingOutlined, UserOutlined } from '@ant-design/icons'
import { Avatar, Button, Drawer, Dropdown, Tag } from 'antd'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation, useMatch } from 'react-router-dom'
import { useIdentity } from '../components/Authentication'
import { Brand } from '../components/Brand'
import { LinkButton } from '../components/LinkButton'
import { LogoutButton } from '../components/LogoutButton'
import { routePaths, uploadPath } from '../routes/routePaths'

const destinations = [
  { key: 'home', label: '平台概览', to: routePaths.home },
  { key: 'workspaces', label: '工作空间', to: routePaths.workspaces },
  { key: 'artifacts', label: '公共文件库', to: routePaths.platformArtifacts },
  { key: 'uploads', label: '上传记录', to: routePaths.uploads },
]

function PlatformNavigation({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation()
  const selected = pathname === '/' ? 'home' : pathname.startsWith('/w/') || pathname === '/workspaces' ? 'workspaces' : pathname.startsWith('/artifacts') ? 'artifacts' : pathname === '/uploads' ? 'uploads' : ''
  return <nav className="platform-navigation" aria-label="平台导航">{destinations.map(item =>
    <Link key={item.key} to={item.to} className={`platform-navigation-link${selected === item.key ? ' is-active' : ''}`}
      aria-current={selected === item.key ? 'page' : undefined} onClick={onNavigate}>{item.label}</Link>,
  )}</nav>
}

function AccountMenu() {
  const user = useIdentity()
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  if (!user) return null
  const role = user.role === 'admin' ? '管理员' : '普通用户'
  const closeOnEscape = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') { event.stopPropagation(); setOpen(false); trigger.current?.focus() }
  }
  return <Dropdown open={open} onOpenChange={setOpen} trigger={['click']} placement="bottomRight"
    menu={{ onClick: () => setOpen(false), items: [
      { key: 'account', icon: <UserOutlined />, label: <Link to={routePaths.account}>个人账号</Link> },
      ...(user.role === 'admin' ? [{ key: 'admin', icon: <SettingOutlined />, label: <Link to={routePaths.adminUsers}>账号管理</Link> }] : []),
    ] }}
    popupRender={menu => <div className="account-popover" onKeyDown={closeOnEscape}>
      <div className="account-popover-identity"><strong title={user.display_name}>{user.display_name}</strong><span title={user.username}>@{user.username}</span><Tag>{role}</Tag></div>
      {menu}
    </div>}>
    <Button ref={trigger} className="account-menu-trigger" type="text" aria-label={`账号菜单：${user.display_name}`} aria-haspopup="menu" aria-expanded={open} onKeyDown={closeOnEscape}>
      <Avatar size={28} className="account-avatar">{Array.from(user.display_name || user.username)[0]}</Avatar>
      <span className="account-trigger-copy" title={user.display_name}>{user.display_name}</span>
      <Tag className="account-role">{role}</Tag><DownOutlined className="account-chevron" />
    </Button>
  </Dropdown>
}

/** Shared chrome; the authenticated API and upload providers live above both route layouts. */
export function ApplicationShell({ children, sidebar }: { children: ReactNode; sidebar?: ReactNode }) {
  const location = useLocation()
  const workspace = useMatch('/w/:workspaceId/*')
  const [compact, setCompact] = useState(() => window.matchMedia('(max-width: 1199px)').matches)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const navigationButton = useRef<HTMLButtonElement>(null)
  const user = useIdentity()
  const uploading = /(?:^|\/)upload$/.test(location.pathname)
  useEffect(() => {
    const media = window.matchMedia('(max-width: 1199px)')
    const update = () => { setCompact(media.matches); if (!media.matches) setDrawerOpen(false) }
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  useEffect(() => { setDrawerOpen(false) }, [location.pathname, location.search])
  const uploadLabel = <span className="global-upload-label">上传文件</span>
  return <div className="application-shell">
    <a className="skip-navigation" href="#main-content">跳到主要内容</a>
    <header className="application-header">
      <div className="application-header-start">
        {compact && <Button ref={navigationButton} className="navigation-toggle" type="text" icon={<MenuOutlined />} aria-label="打开导航" aria-expanded={drawerOpen} aria-controls="application-drawer" onClick={() => setDrawerOpen(true)} />}
        <Brand />
      </div>
      {!compact && <PlatformNavigation />}
      <div className="application-header-actions">
        {uploading ? <Button type="primary" className="global-upload" disabled icon={<CloudUploadOutlined />} aria-label="上传文件（当前页面）">{uploadLabel}</Button> :
          <LinkButton className="global-upload" to={uploadPath(workspace?.params.workspaceId, { returnTo: location.pathname + location.search })} type="primary" icon={<CloudUploadOutlined />} aria-label="上传文件">{uploadLabel}</LinkButton>}
        {user && <><span className="header-divider" /><AccountMenu /><LogoutButton compact /></>}
      </div>
    </header>
    <div className={`application-body${sidebar && !compact ? ' has-sidebar' : ''}`}>
      {sidebar && !compact && <aside className="workspace-sidebar" aria-label="工作空间导航">{sidebar}</aside>}
      <main className="application-main" id="main-content" tabIndex={-1}>{children}</main>
    </div>
    <Drawer title="导航" placement="left" width={304} open={compact && drawerOpen} onClose={() => setDrawerOpen(false)}
      afterOpenChange={open => { if (!open) navigationButton.current?.focus() }} destroyOnHidden className="navigation-drawer">
      <div id="application-drawer"><PlatformNavigation onNavigate={() => setDrawerOpen(false)} />{sidebar && <div className="drawer-workspace-navigation">{sidebar}</div>}</div>
    </Drawer>
  </div>
}
