import { LinkButton } from '../components/LinkButton'
import { useQuery } from '@tanstack/react-query'
import { Alert,App as AntApp,Button,Card,Descriptions,Input,Space,Table,Tag,Typography } from 'antd'
import { useEffect } from 'react'
import { Link,useLocation,useParams,useSearchParams } from 'react-router-dom'
import { useApi } from '../api/context'
import { OccurrenceSummaryTable } from '../components/OccurrenceSummary'
import { EmptyState,ErrorState,HashValue,LoadingState,PageTitle } from '../components/ui'
import { lastList,rememberList,useCursorNavigation } from '../routes/listNavigation'
import { routePaths,uploadPath } from '../routes/routePaths'
import type { SymbolIssue,Workspace } from '../types'
import { ArtifactTable } from './ArtifactPage'
import { useMutation } from '@tanstack/react-query'

export const symbolReasonLabels: Record<string, string> = { missing_pe: '缺少程序文件', missing_pdb: '缺少 PDB', pe_mismatch: '程序身份不匹配', pdb_mismatch: 'PDB 身份不匹配' }
function Reasons({ issue }: { issue: SymbolIssue }) {
  return <Space wrap size={[0, 4]}>{Object.entries(issue.reasons).map(([reason, count]) => <Tag key={reason} color={reason.includes('mismatch') ? 'red' : 'orange'}>{symbolReasonLabels[reason] ?? reason} · {count}</Tag>)}</Space>
}
function suggestion(issue: SymbolIssue) {
  if (Object.keys(issue.reasons).some(reason => reason.includes('mismatch'))) return '核对身份与来源，查看配对证据'
  return issue.reasons.missing_pe ? '补传对应 EXE / DLL' : '补传对应 PDB'
}

export function SymbolHealthPage({ workspace }: { workspace: Workspace }) {
  const api = useApi()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const pagination = useCursorNavigation()
  useEffect(() => rememberList(location.pathname + location.search), [location.pathname, location.search])
  const filters = { q: params.get('q') || undefined, cursor: params.get('cursor') || undefined }
  const query = useQuery({ queryKey: ['symbol-issues', workspace.id, filters], queryFn: () => api.getSymbolIssues(workspace.id, filters), refetchInterval: 5000 })
  return <div>
    <PageTitle kicker="SYMBOL CENTER" title="符号问题" description="仅列出当前报告仍受影响的模块，按影响记录数排序。文件入库与报告更新分别跟踪。" />
    <Card className="section-card"><div className="list-toolbar"><Space wrap><Tag>{query.data?.total ?? '—'} 个模块待处理</Tag><Typography.Text type="secondary">影响 {query.data?.affected_occurrence_count ?? '—'} 份报告（已去重）</Typography.Text></Space><Input.Search aria-label="搜索问题模块" placeholder="搜索模块或 PDB" defaultValue={filters.q} key={filters.q} allowClear onSearch={q => setParams(q.trim() ? { q: q.trim() } : {})} style={{ width: 250 }} /></div>
      {query.isPending ? <LoadingState rows={4} /> : query.isError ? <ErrorState description="符号问题加载失败" onRetry={() => void query.refetch()} /> : !query.data.items.length ? <EmptyState description={filters.q ? '当前搜索没有符号问题' : query.data.analyzed_occurrence_count ? '当前报告没有待处理的符号问题' : '尚无分析结果，暂时无法判断符号影响'} action={filters.q ? <Button onClick={() => setParams({})}>清除搜索</Button> : <Space><LinkButton to={routePaths.artifacts(workspace.id)}>查看文件库</LinkButton>{!query.data.analyzed_occurrence_count && <LinkButton to={uploadPath(workspace.id, { intent: 'dump', returnTo: routePaths.symbols(workspace.id) })} type="primary">上传 DMP</LinkButton>}</Space>} /> : <Table<SymbolIssue> rowKey="id" dataSource={query.data.items} pagination={false} scroll={{ x: 640 }} columns={[
        { title: '模块', render: (_, row) => <Link to={routePaths.symbolIssue(workspace.id, row.id)}><Typography.Text strong>{row.code_file ?? row.debug_file ?? '未知模块'}</Typography.Text><br /><Typography.Text type="secondary">{row.debug_file}</Typography.Text></Link> },
        { title: '当前报告中的问题', width: 220, render: (_, row) => <Reasons issue={row} /> },
        { title: '影响报告', width: 100, render: (_, row) => <Link to={`${routePaths.occurrences(workspace.id)}?symbol_issue_id=${encodeURIComponent(row.id)}`}>{row.affected_occurrence_count} 份</Link> },
        { title: '处理建议', width: 220, render: (_, row) => <Link to={routePaths.symbolIssue(workspace.id, row.id)}>{suggestion(row)} →</Link> },
      ]} />}
      <div className="inbox-pagination"><Button disabled={!pagination.hasPrevious} onClick={pagination.previous}>上一页</Button><Typography.Text type="secondary">按当前采用报告判断，不统计历史问题</Typography.Text><Button disabled={!query.data?.next_cursor} onClick={() => query.data?.next_cursor && pagination.next(query.data.next_cursor)}>下一页</Button></div>
    </Card>
  </div>
}

export function SymbolIssuePage({ workspace }: { workspace: Workspace }) {
  const { issueId = '' } = useParams()
  const location = useLocation()
  const api = useApi()
  const { message } = AntApp.useApp()
  const query = useQuery({ queryKey: ['symbol-issue', workspace.id, issueId], queryFn: () => api.getSymbolIssue(workspace.id, issueId), refetchInterval: 5000 })
  const reports = useQuery({ queryKey: ['occurrences', workspace.id, 'issue', issueId], queryFn: () => api.listOccurrences(workspace.id, { symbol_issue_id: issueId, limit: 8 }), refetchInterval: 5000, enabled: Boolean(query.data) })
  const reprocess = useMutation({ mutationFn: () => api.batchReprocessSymbols(workspace.id, { symbol_issue_id: issueId }), onSuccess: result => {
    message.success(`已为 ${result.affected_occurrence_count} 份报告请求分析，可在下方查看进展`)
    void reports.refetch(); void query.refetch()
  } })
  const back = lastList(routePaths.symbols(workspace.id))
  if (query.isPending) return <LoadingState rows={6} title />
  if (query.isError || !query.data) return <div><Link to={back}>返回符号问题</Link><ErrorState description="符号问题不存在于当前空间，或暂时无法读取" onRetry={() => void query.refetch()} /></div>
  const { issue, files } = query.data
  const ready = query.data.availability === 'symbols_available'
  const conflict = query.data.availability === 'identity_conflict'
  const reportList = `${routePaths.occurrences(workspace.id)}?symbol_issue_id=${encodeURIComponent(issue.id)}`
  return <div>
    <Link className="back-button" to={back}>返回符号问题</Link>
    <PageTitle kicker="SYMBOL ISSUE" title={issue.code_file ?? issue.debug_file ?? '符号问题'} description={`当前影响 ${issue.affected_occurrence_count} 份报告；统计以当前采用报告为准。`} extra={<LinkButton to={uploadPath(workspace.id, { intent: 'symbols', issue: issue.id, returnTo: location.pathname })} type="primary">补传符号文件</LinkButton>} />
    <Alert className="page-alert" showIcon type={!issue.affected_occurrence_count ? 'success' : conflict ? 'warning' : 'info'} message={!issue.affected_occurrence_count ? '当前报告中的问题已解决' : conflict ? '存在身份冲突，请先核对文件证据' : ready ? '相关符号文件已可用，当前报告仍需更新' : suggestion(issue)} description={issue.affected_occurrence_count ? '补传后系统会自动分析相关 DMP。下方报告状态持续更新；如果最近尝试失败或需要复核，请打开对应报告处理。只有新的报告被采用并解决问题后，影响数量才会减少。' : '保留此问题地址供查看；它已从待处理列表中移除。'} />
    <Card title="问题与精确身份" className="section-card"><Space direction="vertical" size="middle"><Reasons issue={issue} /><Descriptions column={{ xs: 1, md: 2 }} size="small"><Descriptions.Item label="Code ID"><HashValue value={issue.code_id} length={64} /></Descriptions.Item><Descriptions.Item label="Debug ID"><HashValue value={issue.debug_id} length={64} /></Descriptions.Item><Descriptions.Item label="首次发现">{new Date(issue.first_seen).toLocaleString()}</Descriptions.Item><Descriptions.Item label="最近发现">{new Date(issue.last_seen).toLocaleString()}</Descriptions.Item></Descriptions>{!issue.code_id && !issue.debug_id && <Typography.Text type="secondary">缺少完整身份，无法仅凭文件名确定配对文件。</Typography.Text>}</Space></Card>
    <Card title="当前空间的相关文件" className="section-card" extra={<Link to={`${routePaths.artifacts(workspace.id)}?symbol_issue_id=${encodeURIComponent(issue.id)}`}>在文件库查看</Link>}><ArtifactTable items={files.items} workspaceId={workspace.id} />{files.next_cursor && <Link to={`${routePaths.artifacts(workspace.id)}?symbol_issue_id=${encodeURIComponent(issue.id)}`}>查看全部相关文件</Link>}</Card>
    <Card title="受影响报告与分析进展" extra={<Link to={reportList}>查看全部 {issue.affected_occurrence_count} 份</Link>}>
      {reports.isPending ? <LoadingState rows={3} /> : reports.isError ? <ErrorState description="受影响报告加载失败" onRetry={() => void reports.refetch()} /> : <OccurrenceSummaryTable workspaceId={workspace.id} items={reports.data?.items ?? []} />}
      <Space wrap style={{ marginTop: 20 }}><Button disabled={!issue.affected_occurrence_count} loading={reprocess.isPending} onClick={() => reprocess.mutate()}>请求重新分析受影响报告</Button><Typography.Text type="secondary">保留原有报告和历史分析证据</Typography.Text></Space>
      {reprocess.isError && <Alert type="error" message={reprocess.error.message} />}
    </Card>
  </div>
}
