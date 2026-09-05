import { useQueryClient } from '@tanstack/react-query'
import { Alert,Button,Card,Input,Modal,Progress,Select,Space,Table,Tag,Typography,Upload } from 'antd'
import { useRef,useState,type InputHTMLAttributes } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../api/context'
import { useCreateWorkspace,useWorkspaces } from '../api/hooks'
import { availabilityLabels,supportedUpload,uploadFile,uploadKind,type UploadState } from '../api/uploadFiles'
import { PageTitle } from '../components/ui'
import { routePaths } from '../routes/routePaths'
import type { Workspace } from '../types'

type Row = UploadState & { key: string; file: File }
export function UploadPage({ workspace }: { workspace?: Workspace }) {
  const api = useApi(); const queries = useQueryClient(); const spaces = useWorkspaces(); const create = useCreateWorkspace()
  const [target, setTarget] = useState<string | undefined>(workspace?.id)
  const [version, setVersion] = useState(''); const [rows, setRows] = useState<Row[]>([])
  const [busy, setBusy] = useState(false); const [creating, setCreating] = useState(false); const [name, setName] = useState('')
  const folder = useRef<HTMLInputElement>(null)
  const batchStarted = rows.some(row => row.uploadId !== undefined)
  const destination = workspace?.id ?? target
  const publicDump = destination === 'public' && rows.some(row => uploadKind(row.file) === 'dmp')
  const addFiles = (files: File[]) => setRows(current => [...current, ...files.filter(supportedUpload).map(file => ({ key: crypto.randomUUID(), file, state: '待上传' as const, progress: 0 }))])
  const update = (key: string, patch: Partial<UploadState>) => setRows(current => current.map(row => row.key === key ? { ...row, ...patch } : row))
  const upload = async () => {
    if (!destination || publicDump) return
    setBusy(true)
    const completed: { key: string; uploadId: string }[] = rows.flatMap(row => row.uploadId && row.state === '已入库' ? [{ key: row.key, uploadId: row.uploadId }] : [])
    try {
      for (const row of rows.filter(row => row.state !== '已入库')) {
        const result = await uploadFile(api, row.file, destination === 'public' ? null : destination, version.trim() || null, patch => update(row.key, patch))
        if (result) completed.push({ key: row.key, uploadId: result.upload_id })
      }
      for (const item of completed) {
        try { update(item.key, { result: await api.getUpload(item.uploadId) }) } catch { /* Refresh failure does not revoke acceptance. */ }
      }
      await queries.invalidateQueries()
    } finally { setBusy(false) }
  }
  const receipt = () => {
    const data = { target: destination, version: version.trim() || null, files: rows.map(({ file, state, result, error, uploadId }) => ({ filename: file.name, state, upload_id: uploadId, result, error })) }
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = 'crashcap-upload.json'; link.click(); URL.revokeObjectURL(url)
  }
  return <div className={workspace ? undefined : 'platform-page'}>
    {!workspace && <Link to={routePaths.home}>返回平台</Link>}
    <PageTitle kicker="UPLOAD" title="上传文件" description="选择空间，上传文件，附带可选版本。EXE、DLL 和 PDB 可以分别上传，系统会按真实身份配对。" />
    <Card><Space direction="vertical" size="large" style={{ width: '100%' }}>
      {workspace ? <Typography.Text strong>目标：{workspace.display_name ?? workspace.name}</Typography.Text> : <Space wrap><Select aria-label="目标空间" placeholder="选择 Workspace 或公共空间" value={target} onChange={setTarget} disabled={busy || batchStarted} style={{ minWidth: 260 }} options={[{ value: 'public', label: '公共空间（EXE / DLL / PDB）' }, ...(spaces.data ?? []).map(space => ({ value: space.id, label: space.display_name ?? space.name }))]} /><Button disabled={busy || batchStarted} onClick={() => setCreating(true)}>新建 Workspace</Button>{spaces.isError && <Typography.Text type="danger">空间列表加载失败</Typography.Text>}</Space>}
      {batchStarted && <Typography.Text type="secondary">本批目标和版本已固定；清空列表后可开始新的批次。</Typography.Text>}
      <label>版本（可选）<Input aria-label="版本（可选）" placeholder="例如 11.0.1.27；留空为未声明版本" maxLength={200} value={version} disabled={busy || batchStarted} onChange={event => setVersion(event.target.value)} style={{ marginTop: 8 }} /></label>
      <Upload.Dragger multiple accept=".exe,.dll,.pdb,.dmp" showUploadList={false} disabled={busy} beforeUpload={file => { addFiles([file]); return false }}><p>点击或拖入 EXE、DLL、PDB、DMP 文件</p><Typography.Text type="secondary">每个文件独立验收；等待配对也表示文件已成功入库。</Typography.Text></Upload.Dragger>
      <input ref={folder} type="file" multiple hidden {...({ webkitdirectory: '' } as InputHTMLAttributes<HTMLInputElement>)} onChange={event => { addFiles(Array.from(event.target.files ?? [])); event.target.value = '' }} />
      <Space wrap><Button disabled={busy} onClick={() => folder.current?.click()}>选择目录</Button><Button disabled={busy || !rows.length} onClick={() => setRows([])}>清空列表</Button><Button type="primary" disabled={!destination || !rows.length || publicDump} loading={busy} onClick={() => void upload()}>上传 {rows.filter(row => row.state !== '已入库').length} 个文件</Button><Button disabled={busy || !rows.some(row => row.uploadId)} onClick={receipt}>下载上传结果</Button></Space>
      {publicDump && <Alert type="warning" showIcon message="公共空间不接收 DMP。请改选 Workspace 后上传本批文件。" />}
      <Table<Row> rowKey="key" dataSource={rows} pagination={{ pageSize: 20 }} scroll={{ x: 800 }} columns={[
        { title: '文件', render: (_, row) => <span>{row.file.webkitRelativePath || row.file.name}<br /><Typography.Text type="secondary">{(row.file.size / 1024).toFixed(1)} KB</Typography.Text></span> },
        { title: '状态', render: (_, row) => <Space direction="vertical"><Tag color={row.state === '失败' ? 'red' : row.state === '已入库' ? 'green' : 'blue'}>{row.state}</Tag>{row.state === '上传中' && <Progress percent={row.progress} size="small" style={{ width: 120 }} />}{row.result?.availability && <Tag color={row.result.availability === 'identity_conflict' ? 'orange' : undefined}>{availabilityLabels[row.result.availability]}</Tag>}{row.error && <Typography.Text type="danger">{row.error}</Typography.Text>}</Space> },
        { title: '结果', render: (_, row) => <Space direction="vertical">{row.result?.occurrence_id && row.result.workspace_id && <Link to={routePaths.occurrence(row.result.workspace_id, row.result.occurrence_id)}>查看报告</Link>}{row.result?.artifact_entry_id && <Link to={row.result.workspace_id ? routePaths.artifacts(row.result.workspace_id) : routePaths.platformArtifacts}>查看产物与符号</Link>}{row.result?.version_conflict && <Typography.Text type="warning">当前版本为 {row.result.current_version ?? '未声明版本'}，未被本次标签覆盖。</Typography.Text>}{row.result?.duplicate && <Typography.Text type="secondary">已有相同内容</Typography.Text>}</Space> },
      ]} />
    </Space></Card>
    <Modal title="新建 Workspace" open={creating} onCancel={() => setCreating(false)} confirmLoading={create.isPending} onOk={() => create.mutate({ name }, { onSuccess: space => { setTarget(space.id); setCreating(false); setName('') } })}><Input aria-label="Workspace 名称" placeholder="精确名称，例如 light-streamer" value={name} onChange={event => setName(event.target.value)} /><Typography.Paragraph type="secondary">使用小写字母、数字和连字符。</Typography.Paragraph>{create.error && <Alert type="error" message={create.error.message} />}</Modal>
  </div>
}
