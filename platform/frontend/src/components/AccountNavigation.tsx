import { Space, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { useIdentity } from './Authentication'
export function AccountNavigation() {
  const user = useIdentity()
  if (!user) return null
  return <nav aria-label="账号导航" style={{ padding: '8px 24px', textAlign: 'right', background: '#fff', borderBottom: '1px solid #eee' }}><Space>
    <Link to="/">平台主页</Link><Typography.Text>{user.display_name}</Typography.Text><Link to="/uploads">上传记录</Link><Link to="/account">个人账号</Link>
    {user.role === 'admin' && <Link to="/admin/users">账号管理</Link>}
  </Space></nav>
}
