import { UserSelect } from '../components/UserSelect'
import { LinkButton } from '../components/LinkButton'
import { useQuery } from '@tanstack/react-query'
import { Alert,Button,Card,Descriptions,Input,List,Select,Space,Table,Tag,Typography } from 'antd'
import { useEffect,useState } from 'react'
import { Link,useLocation,useParams,useSearchParams } from 'react-router-dom'
import { useApi } from '../api/context'
import { availabilityLabels } from '../api/uploadFiles'
import { EmptyState,ErrorState,HashValue,LoadingState,PageTitle } from '../components/ui'
import { lastList,rememberList,useCursorNavigation } from '../routes/listNavigation'
import { routePaths,uploadPath } from '../routes/routePaths'
import type { ArtifactEntry,ArtifactFilters,Workspace } from '../types'

export function ArtifactStatus({ value }: { value: string }) {
  return <Tag color={value === 'symbols_available' ? 'green' : value === 'identity_conflict' ? 'red' : value === 'storage_unavailable' ? 'orange' : undefined}>{availabilityLabels[value] ?? value}</Tag>
}

export function ArtifactTable({ items, workspaceId }: { items: ArtifactEntry[]; workspaceId?: string }) {
  return <Table<ArtifactEntry> rowKey="id" dataSource={items} pagination={false} scroll={{ x: 640 }} columns={[
    { title: '文件', render: (_, row) => <Link to={workspaceId ? routePaths.artifact(workspaceId, row.id) : routePaths.platformArtifact(row.id)}><Typography.Text strong>{row.name}</Typography.Text><br /><Typography.Text type="secondary">{row.kind === 'pe' ? '程序 PE' : 'PDB'} · {(row.size / 1024).toFixed(1)} KB</Typography.Text></Link> },
    { title: '上传人', dataIndex: 'uploaded_by', render: value => value?.display_name ?? '历史未知用户' },
    { title: '版本', dataIndex: 'version', width: 135, render: value => value ?? '未声明版本' },
    { title: '来源', dataIndex: 'workspace_id', width: 95, render: value => <Tag>{value ? '本空间' : '公共'}</Tag> },
    { title: workspaceId ? '在本空间的可用性' : '公共可用性', dataIndex: 'availability', width: 165, render: value => <ArtifactStatus value={value} /> },
    { title: '上传时间', dataIndex: 'created_at', width: 155, responsive: ['xl'], render: value => new Date(value).toLocaleString() },
  ]} />
}

export function ArtifactPage({ workspace }: { workspace?: Workspace }) {
  const api = useApi()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const pagination = useCursorNavigation()
  const [name, setName] = useState(params.get('filename') ?? '')
  const [version, setVersion] = useState(params.get('version') ?? '')
  useEffect(() => { setName(params.get('filename') ?? ''); setVersion(params.get('version') ?? '') }, [params])
  useEffect(() => rememberList(location.pathname + location.search), [location.pathname, location.search])
  const filters: ArtifactFilters = {
    uploaded_by_user_id: params.get('uploaded_by_user_id') || undefined,
    origin: (params.get('origin') ?? 'all') as ArtifactFilters['origin'], filename: params.get('filename') || undefined,
    version: params.get('version') || undefined, kind: params.get('kind') as ArtifactFilters['kind'] || undefined,
    availability: params.get('availability') || undefined, symbol_issue_id: params.get('symbol_issue_id') || undefined,
    cursor: params.get('cursor') || undefined,
  }
  const query = useQuery({ queryKey: ['artifacts', workspace?.id, filters], queryFn: () => api.browseArtifacts(workspace?.id, filters), refetchInterval: 5000 })
  const change = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params); next.delete('cursor')
    Object.entries(patch).forEach(([key, value]) => { if (value) next.set(key, value); else next.delete(key) })
    setParams(next)
  }
  const upload = uploadPath(workspace?.id, { intent: 'symbols', target: workspace ? undefined : 'public', returnTo: location.pathname + location.search })
  const filtered = Boolean(filters.uploaded_by_user_id || filters.filename || filters.version || filters.kind || filters.availability || filters.symbol_issue_id || filters.origin !== 'all')
  return <div className={workspace ? undefined : 'platform-page'}>
    {!workspace && <Link to={routePaths.home}>返回平台</Link>}
    <PageTitle kicker={workspace ? 'SYMBOL CENTER' : 'PUBLIC FILES'} title={workspace ? '文件库' : '公共文件库'} description={workspace ? '已入库的 EXE、DLL 与 PDB。默认包含本空间和公共文件，可用性按当前空间判断。' : '所有 Workspace 均可使用的程序与符号文件。DMP 请上传到具体 Workspace。'} extra={<LinkButton to={upload}>上传程序与 PDB</LinkButton>} />
    <Card className="section-card"><Space wrap className="file-filters">
      <UserSelect value={filters.uploaded_by_user_id} onChange={id => change({ uploaded_by_user_id: id })} /><Input.Search aria-label="搜索文件名" placeholder="搜索文件名" value={name} onChange={event => setName(event.target.value)} onSearch={() => change({ filename: name.trim() || undefined })} style={{ width: 220 }} allowClear />
      <Input aria-label="文件版本" placeholder="版本，回车搜索" value={version} onChange={event => setVersion(event.target.value)} onPressEnter={() => change({ version: version.trim() || undefined })} style={{ width: 165 }} />
      {workspace && <Select aria-label="文件来源" value={filters.origin} onChange={origin => change({ origin })} style={{ width: 135 }} options={[{ value: 'all', label: '全部来源' }, { value: 'workspace', label: '本空间' }, { value: 'public', label: '公共文件' }]} />}
      <Select aria-label="文件类型" placeholder="全部类型" allowClear value={filters.kind} onChange={kind => change({ kind })} style={{ width: 125 }} options={[{ value: 'pe', label: 'EXE / DLL' }, { value: 'pdb', label: 'PDB' }]} />
      <Select aria-label="可用性" placeholder="全部可用状态" allowClear value={filters.availability} onChange={availability => change({ availability })} style={{ width: 155 }} options={Object.entries(availabilityLabels).filter(([value]) => value !== 'validating').map(([value, label]) => ({ value, label }))} />
      {filtered && <Button onClick={() => setParams({})}>清除筛选</Button>}
    </Space>
      {query.isPending ? <LoadingState rows={4} /> : query.isError ? <ErrorState description="文件库加载失败" onRetry={() => void query.refetch()} /> : query.data.items.length ? <ArtifactTable items={query.data.items} workspaceId={workspace?.id} /> : <EmptyState description={filtered ? '当前筛选没有文件' : '尚无程序或符号文件'} action={filtered ? <Button onClick={() => setParams({})}>清除筛选</Button> : <LinkButton to={upload} type="primary">上传第一份文件</LinkButton>} />}
      <div className="inbox-pagination"><Button disabled={!pagination.hasPrevious} onClick={pagination.previous}>上一页</Button><Typography.Text type="secondary">DMP 与分析结果请在崩溃记录中查看</Typography.Text><Button disabled={!query.data?.next_cursor} onClick={() => query.data?.next_cursor && pagination.next(query.data.next_cursor)}>下一页</Button></div>
    </Card>
  </div>
}

export function ArtifactDetailPage({ workspace }: { workspace?: Workspace }) {
  const { artifactId = '' } = useParams()
  const api = useApi()
  const location = useLocation()
  const query = useQuery({ queryKey: ['artifact-detail', workspace?.id, artifactId], queryFn: () => api.getArtifact(workspace?.id, artifactId), refetchInterval: 5000 })
  const back = lastList(workspace ? routePaths.artifacts(workspace.id) : routePaths.platformArtifacts)
  if (query.isPending) return <LoadingState rows={6} title />
  if (query.isError || !query.data) return <div><Link to={back}>返回文件库</Link><ErrorState description="文件不存在于当前空间，或暂时无法读取" onRetry={() => void query.refetch()} /></div>
  const { artifact, pairs } = query.data
  return <div className={workspace ? undefined : 'platform-page'}>
    <Link className="back-button" to={back}>返回文件库</Link>
    <PageTitle kicker="FILE DETAILS" title={artifact.name} description="文件验收成功；下方状态表示其在当前空间的符号可用性。" extra={<ArtifactStatus value={artifact.availability} />} />
    {artifact.availability !== 'symbols_available' && <Alert className="page-alert" type={artifact.availability === 'identity_conflict' ? 'warning' : 'info'} showIcon message={availabilityLabels[artifact.availability]} description={artifact.availability === 'waiting_for_pair' ? `请补传身份一致的${artifact.kind === 'pe' ? ' PDB' : ' EXE / DLL'}，文件名和版本不参与配对。` : artifact.availability === 'identity_conflict' ? '同一身份存在不同有效内容。请检查来源和配对证据；重新上传不会自动覆盖冲突。' : artifact.availability === 'no_debug_identity' ? '文件可保留，但没有可用于完整符号配对的调试身份。' : '文件已入库，当前存储暂不可用。'} action={<LinkButton to={uploadPath(workspace?.id, { intent: 'symbols', target: workspace ? undefined : 'public', returnTo: location.pathname })}>补传文件</LinkButton>} />}
    <Card title="文件信息" className="section-card"><Descriptions column={{ xs: 1, md: 2 }} size="small">
      <Descriptions.Item label="来源空间">{artifact.workspace_id ? workspace?.display_name ?? workspace?.name : '公共空间'}</Descriptions.Item>
      <Descriptions.Item label="版本">{artifact.version ?? '未声明版本'}</Descriptions.Item>
      <Descriptions.Item label="上传人">{artifact.uploaded_by?.display_name ?? '历史未知用户'}</Descriptions.Item><Descriptions.Item label="上传方式">{artifact.source}</Descriptions.Item><Descriptions.Item label="上传时间">{new Date(artifact.created_at).toLocaleString()}</Descriptions.Item>
      <Descriptions.Item label="Code ID"><HashValue value={artifact.code_id} length={64} /></Descriptions.Item><Descriptions.Item label="Debug ID"><HashValue value={artifact.debug_id} length={64} /></Descriptions.Item>
      <Descriptions.Item label="SHA-256" span={2}><Typography.Text code copyable className="break-identity">{artifact.sha256}</Typography.Text></Descriptions.Item>
    </Descriptions></Card>
    <Card title="可见配对与来源"><List dataSource={pairs} locale={{ emptyText: '当前空间尚无可见配对' }} renderItem={pair => <List.Item><Space direction="vertical" style={{ width: '100%' }}><Typography.Text type="secondary">配对 <HashValue value={pair.id} /> · {pair.state}</Typography.Text><ArtifactTable items={[...pair.pe, ...pair.pdb]} workspaceId={workspace?.id} /></Space></List.Item>} /></Card>
  </div>
}
