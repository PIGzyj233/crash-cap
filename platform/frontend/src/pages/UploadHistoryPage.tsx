import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Space, Table, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../api/context'
import { UserSelect } from '../components/UserSelect'
import { routePaths } from '../routes/routePaths'
import { PageTitle } from '../components/ui'

const states: Record<string, string> = { INITIALIZED: '已初始化', UPLOADING: '传输中', UPLOADED: '等待验证', VERIFYING: '验证中', ACCEPTED: '已入库', QUARANTINED: '已隔离', REJECTED: '已拒收' }
export function UploadHistoryPage() {
  const api = useApi()
  const [params, setParams] = useSearchParams()
  const userId = params.get('uploaded_by_user_id') ?? undefined
  const cursor = params.get('cursor') ?? undefined
  const history = useQuery({ queryKey: ['upload-history', userId, cursor], queryFn: () => api.listUploads({ uploaded_by_user_id: userId, cursor }), refetchInterval: 10000 })
  return <div className="platform-page"><PageTitle title="上传记录" description="查看文件提交、验收状态与分析结果。" /><Card>
    <Space style={{ marginBottom: 20 }}><UserSelect value={userId} onChange={id => setParams(id ? { uploaded_by_user_id: id } : {})} /><Button onClick={() => void history.refetch()}>刷新</Button></Space>
    {history.error && <Alert type="error" message="无法读取上传记录" />}
    <Table rowKey="upload_id" dataSource={history.data?.items ?? []} loading={history.isPending} pagination={false} scroll={{ x: 900 }} columns={[
      { title: '文件', dataIndex: 'filename' }, { title: '类型', dataIndex: 'file_kind' },
      { title: '上传人', render: (_, row) => row.uploaded_by.display_name },
      { title: '时间', dataIndex: 'uploaded_at', render: value => new Date(value).toLocaleString() },
      { title: '状态', render: (_, row) => <Space direction="vertical"><span>{states[row.status] ?? row.status}</span>{row.rejection_reason && <Typography.Text type="danger">{row.rejection_reason}</Typography.Text>}</Space> },
      { title: '结果', render: (_, row) => row.occurrence_id && row.workspace_id ? <Link to={routePaths.occurrence(row.workspace_id, row.occurrence_id)}>查看崩溃报告</Link> : row.artifact_entry_id ? <Link to={row.workspace_id ? routePaths.artifact(row.workspace_id, row.artifact_entry_id) : routePaths.platformArtifact(row.artifact_entry_id)}>查看文件</Link> : <Typography.Text type="secondary">{row.upload_id}</Typography.Text> },
    ]} />
    <Space style={{ marginTop: 16 }}>{cursor && <Button onClick={() => setParams(userId ? { uploaded_by_user_id: userId } : {})}>返回首页</Button>}{history.data?.next_cursor && <Button onClick={() => setParams({ ...(userId ? { uploaded_by_user_id: userId } : {}), cursor: history.data!.next_cursor! })}>下一页</Button>}</Space>
  </Card></div>
}
