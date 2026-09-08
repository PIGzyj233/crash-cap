import { Outlet } from 'react-router-dom'
import { ApplicationShell } from './ApplicationShell'

export function PlatformLayout() {
  return <ApplicationShell><Outlet /></ApplicationShell>
}
