import { useQuery } from '@tanstack/react-query'
import { CloudUploadOutlined } from '@ant-design/icons'
import { Alert,App as AntApp,Button,Card,Input,Modal,Progress,Select,Space,Table,Typography,Upload } from 'antd'
import { useRef,useState,type InputHTMLAttributes } from 'react'
import { Link,useSearchParams } from 'react-router-dom'
import { useApi } from '../api/context'
import { useCreateWorkspace,useWorkspaces } from '../api/hooks'
import { supportedUpload,uploadKind } from '../api/uploadFiles'
import { useUploadBatch,type QueueRow } from '../api/uploadQueue'
import { PageTitle } from '../components/ui'
import { routePaths,safeReturnPath } from '../routes/routePaths'
import type { Workspace } from '../types'
import { ArtifactStatus } from './ArtifactPage'

export function UploadPage({ workspace }: { workspace?: Workspace }) {
  const api = useApi()
  const [params] = useSearchParams()
  const { message } = AntApp.useApp()
  const spaces = useWorkspaces()
  const create = useCreateWorkspace()
  const key = workspace?.id ?? (params.get('target') === 'public' ? 'public' : 'platform')
  const { batch, patch, addFiles, start, recover } = useUploadBatch(key)
  const { rows, version, target } = batch
  const busy = batch.busy || rows.some(row => row.state === '上传中' || row.state === '校验中')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const folder = useRef<HTMLInputElement>(null)
  const batchStarted = rows.some(row => row.uploadId !== undefined)
  const publicDump = target === 'public' && rows.some(row => /\.dmp$/i.test(row.name))
  const intent = params.get('intent')
  const issueId = params.get('issue')
  const issue = useQuery({ queryKey: ['symbol-issue', workspace?.id, issueId], queryFn: () => api.getSymbolIssue(workspace!.id, issueId!), enabled: Boolean(workspace && issueId) })
  const back = safeReturnPath(params.get('returnTo'), workspace?.id) ?? (workspace ? routePaths.overview(workspace.id) : routePaths.home)
  const title = intent === 'dump' ? '上传 DMP' : intent === 'symbols' ? '上传程序与符号' : '上传文件'
  const selectFiles = (files: File[]) => {
    const accepted = files.filter(file => supportedUpload(file) && (intent === 'dump' ? uploadKind(file) === 'dmp' : intent === 'symbols' ? uploadKind(file) !== 'dmp' : true))
    if (accepted.length !== files.length) message.info(`已选择 ${accepted.length} 个符合当前上传类型的文件`)
    addFiles(accepted)
  }
  const receipt = () => {
    const data = { target, version: version.trim() || null, files: rows.map(({ name, state, result, error, uploadId }) => ({ filename: name, state, upload_id: uploadId, result, error })) }
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = 'crashcap-upload.json'; link.click(); URL.revokeObjectURL(url)
  }
  const pending = rows.filter(row => row.state !== '已入库').length
  return <div className={workspace ? undefined : 'platform-page'}>
    <Link className="back-button" to={back}>返回来源页面</Link>
    <PageTitle kicker="UPLOAD" title={title} description="每个文件独立验收。程序和 PDB 可分批补传，已入库文件会按真实身份自动配对。" />
    {issue.data && <Alert className="page-alert" type="info" showIcon message={`为 ${issue.data.issue.code_file ?? issue.data.issue.debug_file} 补传符号 · 影响 ${issue.data.issue.affected_occurrence_count} 份报告`} description={<Space wrap>Code ID: <Typography.Text code>{issue.data.issue.code_id ?? '未知'}</Typography.Text>Debug ID: <Typography.Text code>{issue.data.issue.debug_id ?? '未知'}</Typography.Text><Link to={routePaths.symbolIssue(workspace!.id, issue.data.issue.id)}>查看问题与进展</Link></Space>} />}
    {issue.isError && <Alert className="page-alert" type="warning" message="无法读取来源符号问题，请先核对文件身份" />}
    <Card className="section-card"><Space direction="vertical" size="large" style={{ width: '100%' }}>
      {workspace ? <Typography.Text strong>目标空间：{workspace.display_name ?? workspace.name}</Typography.Text> : <Space wrap><Select aria-label="目标空间" placeholder="选择 Workspace 或公共空间" value={target} onChange={target => patch({ target })} disabled={busy || batchStarted} style={{ minWidth: 260 }} options={[{ value: 'public', label: '公共空间（EXE / DLL / PDB）' }, ...(spaces.data ?? []).map(space => ({ value: space.id, label: space.display_name ?? space.name }))]} /><Button disabled={busy || batchStarted} onClick={() => setCreating(true)}>新建 Workspace</Button>{spaces.isError && <Typography.Text type="danger">空间列表加载失败</Typography.Text>}</Space>}
      <label className="upload-version">版本（可选）<Input aria-label="版本（可选）" placeholder="例如 11.0.1.27；留空为未声明版本" maxLength={200} value={version} disabled={busy || batchStarted} onChange={event => patch({ version: event.target.value })} style={{ marginTop: 8 }} /></label>
      {batchStarted && <Typography.Text type="secondary">本次上传的空间和版本已固定。清空列表后可开始新的上传。</Typography.Text>}
      <Upload.Dragger multiple accept={intent === 'dump' ? '.dmp' : intent === 'symbols' ? '.exe,.dll,.pdb' : '.exe,.dll,.pdb,.dmp'} showUploadList={false} disabled={busy} beforeUpload={file => { selectFiles([file]); return false }}><CloudUploadOutlined className="upload-drop-icon" /><p>点击或拖入 {intent === 'dump' ? 'DMP' : intent === 'symbols' ? 'EXE、DLL、PDB' : 'EXE、DLL、PDB、DMP'} 文件</p><Typography.Text type="secondary">等待配对表示文件已入库；报告会在相关文件补齐后自动更新。</Typography.Text></Upload.Dragger>
      <input ref={folder} type="file" multiple hidden {...({ webkitdirectory: '' } as InputHTMLAttributes<HTMLInputElement>)} onChange={event => { selectFiles(Array.from(event.target.files ?? [])); event.target.value = '' }} />
      <Space wrap><Button disabled={busy} onClick={() => folder.current?.click()}>选择目录</Button><Button type="primary" disabled={!target || !pending || publicDump || !rows.some(row => row.file && row.state !== '已入库')} loading={busy} onClick={() => void start()}>上传 {pending} 个文件</Button><Button disabled={busy || !rows.length} onClick={() => patch({ rows: [], version: '' })}>清空列表</Button></Space>
      {publicDump && <Alert type="warning" showIcon message="公共空间不接收 DMP。请改选 Workspace 后上传本批文件。" />}
    </Space></Card>
    {rows.length > 0 && <Card title={`本次上传 · ${rows.filter(row => row.state === '已入库').length} / ${rows.length} 已入库`} extra={<Space wrap>{rows.some(row => row.state === '失败' || row.state === '需重新选择') && <Button disabled={busy || publicDump} onClick={() => void start(true)}>重试失败文件</Button>}<Button disabled={busy || !rows.some(row => row.uploadId)} onClick={() => void recover()}>恢复验收状态</Button><Button disabled={busy || !rows.some(row => row.uploadId)} onClick={receipt}>下载上传结果</Button></Space>}>
      <Typography.Paragraph type="secondary">站内切换保留本次队列。刷新后可恢复验收回执；尚未传完的文件需要重新选择。</Typography.Paragraph>
      <Table<QueueRow> rowKey="key" dataSource={rows} pagination={{ pageSize: 20 }} scroll={{ x: 640 }} columns={[
        { title: '文件', render: (_, row) => <span>{row.relativePath}<br /><Typography.Text type="secondary">{(row.size / 1024).toFixed(1)} KB</Typography.Text></span> },
        { title: '传输与验收', width: 210, render: (_, row) => <Space direction="vertical"><Typography.Text type={row.state === '失败' ? 'danger' : row.state === '已入库' ? 'success' : undefined}>{row.state}</Typography.Text>{row.state === '上传中' && <Progress percent={row.progress} size="small" style={{ width: 120 }} />}{row.error && <Typography.Text type="danger">{row.error}</Typography.Text>}</Space> },
        { title: '入库后可用性', width: 150, render: (_, row) => row.result?.availability ? <ArtifactStatus value={row.result.availability} /> : row.result?.occurrence_id ? '已进入分析流程' : '—' },
        { title: '结果', render: (_, row) => <Space direction="vertical">{row.result?.occurrence_id && row.result.workspace_id && <Link to={routePaths.occurrence(row.result.workspace_id, row.result.occurrence_id)}>查看报告</Link>}{row.result?.artifact_entry_id && <Link to={row.result.workspace_id ? routePaths.artifact(row.result.workspace_id, row.result.artifact_entry_id) : routePaths.platformArtifact(row.result.artifact_entry_id)}>查看文件详情</Link>}{row.result?.version_conflict && <Typography.Text type="warning">当前版本为 {row.result.current_version ?? '未声明版本'}，未被本次标签覆盖。</Typography.Text>}{row.result?.duplicate && <Typography.Text type="secondary">已有相同内容</Typography.Text>}</Space> },
      ]} />
    </Card>}
    <Modal title="新建 Workspace" open={creating} onCancel={() => setCreating(false)} confirmLoading={create.isPending} onOk={() => create.mutate({ name }, { onSuccess: space => { patch({ target: space.id }); setCreating(false); setName('') } })}><Input aria-label="Workspace 名称" placeholder="例如 light-streamer" value={name} onChange={event => setName(event.target.value)} /><Typography.Paragraph type="secondary">使用小写字母、数字和连字符。</Typography.Paragraph>{create.error && <Alert type="error" message={create.error.message} />}</Modal>
  </div>
}
