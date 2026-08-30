import { Alert } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { PageTitle } from '../components/ui'
import { routePaths } from '../routes/routePaths'
import { useWorkspaceRoute } from '../layouts/WorkspaceLayout'
import { DumpUploadCard } from './WorkspaceOverviewPage'

export function UploadPage() {
  const workspace = useWorkspaceRoute()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const openOccurrence = (occurrenceId: string) => {
    void queryClient.invalidateQueries({ queryKey: ['platform-overview'] })
    void queryClient.invalidateQueries({ queryKey: ['workspace-overview', workspace.id] })
    void queryClient.invalidateQueries({ queryKey: ['occurrences', workspace.id] })
    navigate(routePaths.occurrence(workspace.id, occurrenceId), { replace: true })
  }
  return <div className="upload-route-page">
    <PageTitle kicker={`${workspace.display_name ?? workspace.name} / UPLOAD`} title="上传 Dump" description="上传、校验、Occurrence 去重与分析进度均绑定到稳定 URL。" />
    <Alert className="page-alert" type="info" showIcon message="同 Workspace 同一份 DMP 只对应一个 Occurrence" description="重传会进入既有 Occurrence；reprocess 只创建新的 Analysis Run。" />
    <DumpUploadCard workspace={workspace} onOpenOccurrence={openOccurrence} />
  </div>
}
