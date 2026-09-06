import { LinkButton } from '../components/LinkButton'
import { Button,Result } from 'antd';
import { Link,useParams } from 'react-router-dom';
import { routePaths } from '../routes/routePaths';

export function NotFoundPage({ title = '页面不存在', description = '请检查链接，或返回稳定入口重新导航。', showWorkspaceLink = true }: { title?: string; description?: string; showWorkspaceLink?: boolean }) {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  return <Result status="404" title="404" subTitle={<span><strong>{title}</strong><br />{description}</span>} extra={<><LinkButton to={routePaths.home} type="primary">返回平台主页</LinkButton>{showWorkspaceLink && workspaceId && <LinkButton to={routePaths.overview(workspaceId)}>返回 Workspace</LinkButton>}</>} />
}
