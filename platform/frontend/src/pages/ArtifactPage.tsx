import { useQuery } from '@tanstack/react-query'
import { Button,Card,Input,Select,Space,Table,Tag,Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../api/context'
import { useWorkspaces } from '../api/hooks'
import { availabilityLabels } from '../api/uploadFiles'
import { ErrorState,HashValue,PageTitle } from '../components/ui'
import { routePaths } from '../routes/routePaths'
import type { ArtifactEntry,Workspace } from '../types'

export function ArtifactPage({ workspace }: { workspace?: Workspace }) {
  const api = useApi(); const spaces = useWorkspaces(); const [scope, setScope] = useState('public')
  const [version, setVersion] = useState(''); const [filename, setFilename] = useState('')
  const [availability, setAvailability] = useState<string>(); const [cursor, setCursor] = useState<string>()
  const params = { workspace_id: workspace?.id ?? (scope === 'public' ? undefined : scope), version, filename, availability, cursor }
  const query = useQuery({ queryKey: ['artifacts', params], queryFn: () => api.listArtifacts(params), refetchInterval: 5_000 })
  const reset = (change: () => void) => { change(); setCursor(undefined) }
  return <div className={workspace ? undefined : 'platform-page'}>
    {!workspace && <Link to={routePaths.home}>返回平台</Link>}
    <PageTitle kicker="ARTIFACTS" title="产物与符号" description="版本用于管理文件；符号按真实身份匹配。Workspace 的分析只使用本空间和公共文件。" />
    <Card><Space wrap style={{ marginBottom: 20 }}>{!workspace && <Select aria-label="产物空间" value={scope} style={{ minWidth: 200 }} onChange={value => reset(() => setScope(value))} options={[{ value: 'public', label: '公共空间' }, ...(spaces.data ?? []).map(space => ({ value: space.id, label: space.display_name ?? space.name }))]} />}<Input aria-label="产物版本" placeholder="版本" value={version} onChange={event => reset(() => setVersion(event.target.value))} style={{ width: 180 }} /><Input aria-label="文件名" placeholder="文件名" value={filename} onChange={event => reset(() => setFilename(event.target.value))} style={{ width: 220 }} /><Select aria-label="可用状态" placeholder="全部可用状态" allowClear value={availability} onChange={value => reset(() => setAvailability(value))} style={{ width: 180 }} options={Object.entries(availabilityLabels).map(([value,label]) => ({ value,label }))} /><Link to={workspace ? routePaths.upload(workspace.id) : routePaths.platformUpload}><Button type="primary">上传文件</Button></Link></Space>
      {query.isError ? <ErrorState description="产物加载失败" onRetry={() => void query.refetch()} /> : <Table<ArtifactEntry> rowKey="id" loading={query.isPending} dataSource={query.data?.items ?? []} pagination={false} scroll={{ x: 1050 }} columns={[
        { title: '文件', dataIndex: 'name', render: (name: string, row) => <span>{name}<br /><Typography.Text type="secondary">{row.kind.toUpperCase()} · {(row.size / 1024).toFixed(1)} KB</Typography.Text></span> },
        { title: '版本', dataIndex: 'version', render: value => value ?? '未声明版本' },
        { title: '状态', dataIndex: 'availability', render: value => <Tag color={value === 'identity_conflict' ? 'orange' : value === 'symbols_available' ? 'green' : undefined}>{availabilityLabels[value]}</Tag> },
        { title: '身份', render: (_, row) => <span>Code ID: <HashValue value={row.code_id} /><br />Debug ID: <HashValue value={row.debug_id} /></span> },
        { title: 'SHA-256', dataIndex: 'sha256', render: value => <HashValue value={value} /> },
        { title: '上传时间', dataIndex: 'created_at', render: value => new Date(value).toLocaleString() },
      ]} />}
      <Space style={{ marginTop: 20 }}><Button disabled={!cursor} onClick={() => setCursor(undefined)}>第一页</Button><Button disabled={!query.data?.next_cursor} onClick={() => setCursor(query.data?.next_cursor ?? undefined)}>下一页</Button></Space>
    </Card>
  </div>
}
