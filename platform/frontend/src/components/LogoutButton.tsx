import { LogoutOutlined } from '@ant-design/icons'
import { App as AntApp, Button } from 'antd'
import { useSyncExternalStore } from 'react'
import { getLogoutPending, logoutCurrentSession, subscribeLogout } from '../api/authTransport'

export function LogoutButton({ compact = false }: { compact?: boolean }) {
  const busy = useSyncExternalStore(subscribeLogout, getLogoutPending, () => false)
  const { message } = AntApp.useApp()
  return <Button className={compact ? 'logout-button logout-button-compact' : 'logout-button'}
    type={compact ? 'text' : 'default'} icon={<LogoutOutlined />} loading={busy} disabled={busy}
    onClick={() => { void logoutCurrentSession().catch(() => { void message.error({ key: 'logout-error', content: '退出失败，请重试' }) }) }}>
    {busy ? '正在退出' : '退出登录'}
  </Button>
}
