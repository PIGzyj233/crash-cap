import { Button, Result } from 'antd'
import { Link, useParams } from 'react-router-dom'
import { routePaths } from '../routes/routePaths'

export function NotFoundPage({ title = '页面不存在', description = '请检查链接，或返回稳定入口重新导航。', showWorkspaceLink = true }: { title?: string; description?: string; showWorkspaceLink?: boolean }) {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  return <Result status="404" title="404" subTitle={<span><strong>{title}</strong><br />{description}</span>} extra={<><Link to={routePaths.home}><Button type="primary">返回平台主页</Button></Link>{showWorkspaceLink && workspaceId && <Link to={routePaths.overview(workspaceId)}><Button>返回 Workspace</Button></Link>}</>} />
}
