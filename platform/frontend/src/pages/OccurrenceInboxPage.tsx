import { LinkButton } from '../components/LinkButton'
import { ClearOutlined,CloudUploadOutlined,LeftOutlined,ReloadOutlined,RightOutlined,SearchOutlined } from '@ant-design/icons'
import { Alert,Button,Card,Col,Collapse,Input,Row,Segmented,Select,Space,Tag,Typography } from 'antd'
import { useEffect,useMemo,useState } from 'react'
import { Link,useLocation,useSearchParams } from 'react-router-dom'
import { CrashCapApiError } from '../api/client'
import { useOccurrences } from '../api/hooks'
import { OccurrenceSummaryTable } from '../components/OccurrenceSummary'
import { EmptyState,ErrorState,LoadingState,PageTitle } from '../components/ui'
import { useWorkspaceRoute } from '../layouts/WorkspaceLayout'
import { parseInboxQuery,serializeInboxQuery } from '../routes/inboxQuery'
import { routePaths,uploadPath } from '../routes/routePaths'
import { rememberList,useCursorNavigation } from '../routes/listNavigation'
import type { OccurrenceListParams } from '../types'

const { Text } = Typography
const LATEST_STATUSES = ['UPLOADED', 'VALIDATING', 'INSPECTED', 'MATCHING_SYMBOLS', 'WAITING_FOR_SYMBOLS', 'SYMBOLS_READY', 'QUEUED', 'ANALYZING', 'NORMALIZING', 'GROUPING', 'COMPLETE', 'PARTIAL', 'FAILED', 'REJECTED', 'CANCELLED', 'TIMEOUT', 'OOM']

export function OccurrenceInboxPage() {
  const workspace = useWorkspaceRoute()
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const pagination = useCursorNavigation()
  useEffect(() => rememberList(location.pathname + location.search), [location.pathname, location.search])
  const parsed = useMemo(() => parseInboxQuery(searchParams), [searchParams])
  const query = useOccurrences(workspace.id, parsed.filters)
  const [draft, setDraft] = useState(() => textDraft(parsed.filters))

  useEffect(() => {
    if (parsed.changed) setSearchParams(parsed.canonical, { replace: true })
  }, [parsed, setSearchParams])
  useEffect(() => setDraft(textDraft(parsed.filters)), [searchParams, parsed.filters])

  const update = (patch: Partial<OccurrenceListParams>, push = false) => {
    const next = { ...parsed.filters, ...patch }
    delete next.cursor
    Object.keys(next).forEach((key) => {
      const typedKey = key as keyof OccurrenceListParams
      if (next[typedKey] === undefined || next[typedKey] === '') delete next[typedKey]
    })
    setSearchParams(serializeInboxQuery(next), { replace: !push })
  }
  const applyText = () => update({
    q: draft.q.trim() || undefined,
    version: draft.version.trim() || undefined,
    version_unset: draft.version.trim() ? undefined : parsed.filters.version_unset,
    test_label: draft.test_label || undefined,
    test_batch: draft.test_batch || undefined,
    from: localDateTimeToIso(draft.from),
    to: localDateTimeToIso(draft.to),
  })
  const clear = () => setSearchParams(new URLSearchParams(), { replace: true })
  const filterCount = Object.entries(parsed.filters).filter(([key, value]) => key !== 'cursor' && value !== undefined).length
  const requestError = query.error instanceof CrashCapApiError ? query.error : null

  return <div>
    <PageTitle kicker="CRASH ANALYSIS" title="崩溃记录" description="查看每份 DMP 的当前报告，以及最近一次分析进展。" extra={<LinkButton to={uploadPath(workspace.id, { intent: 'dump', returnTo: location.pathname + location.search })} icon={<CloudUploadOutlined />}>上传 DMP</LinkButton>} />
    <Segmented className="quick-views" aria-label="崩溃快捷视图" value={parsed.filters.attention ?? 'all'} onChange={value => update({ attention: value === 'all' ? undefined : value as OccurrenceListParams['attention'] })} options={[{ label: '全部记录', value: 'all' }, { label: '分析中', value: 'in_progress' }, { label: '最近失败', value: 'latest_attempt_failed' }, { label: '符号受影响', value: 'symbol_affected' }, { label: '未分组', value: 'unclassified' }]} />
    {parsed.filters.symbol_issue_id && <Alert className="page-alert" type="info" message="正在查看此符号问题影响的记录" action={<Link to={routePaths.symbolIssue(workspace.id, parsed.filters.symbol_issue_id)}>查看符号问题</Link>} />}
    <Card className="section-card inbox-filters" title="筛选与搜索" extra={<Space><Button icon={<ClearOutlined />} onClick={clear} disabled={!filterCount && !parsed.filters.cursor}>清除筛选</Button><Button type="primary" icon={<SearchOutlined />} onClick={applyText}>应用</Button></Space>}>
      <Row gutter={[12, 12]}>
        <Col xs={24} md={6}><label className="filter-label" htmlFor="inbox-q">文本搜索</label><Input id="inbox-q" value={draft.q} onChange={(event) => setDraft((value) => ({ ...value, q: event.target.value }))} onPressEnter={applyText} maxLength={128} placeholder="Occurrence / 异常 / 模块 / 函数 / Version" allowClear /></Col>
        <Col xs={12} md={5}><label className="filter-label" htmlFor="inbox-from">开始时间</label><Input id="inbox-from" type="datetime-local" value={draft.from} onChange={(event) => setDraft((value) => ({ ...value, from: event.target.value }))} /></Col>
        <Col xs={12} md={5}><label className="filter-label" htmlFor="inbox-to">结束时间</label><Input id="inbox-to" type="datetime-local" value={draft.to} onChange={(event) => setDraft((value) => ({ ...value, to: event.target.value }))} /></Col>
        <Col xs={12} md={4}><label className="filter-label" htmlFor="inbox-version">版本</label><Input id="inbox-version" value={draft.version} onChange={(event) => setDraft((value) => ({ ...value, version: event.target.value }))} maxLength={200} placeholder={parsed.filters.version_unset ? '未声明版本' : '精确匹配'} /></Col>
        <Col xs={24} md={4}><label className="filter-label">刷新</label><Button block icon={<ReloadOutlined />} loading={query.isFetching} onClick={() => void query.refetch()}>刷新当前页</Button></Col>
      </Row>
      <Collapse ghost items={[{ key: 'advanced', label: `高级筛选${filterCount ? ` · ${filterCount} 项已应用` : ''}`, children: <Row gutter={[12, 12]}>
        <Col xs={24} md={6}><label className="filter-label">崩溃类型</label><Select aria-label="崩溃类型" allowClear value={parsed.filters.crash_type} onChange={value => update({ crash_type: value })} style={{ width: '100%' }} options={[['crash', 'Crash'], ['hang', 'Hang'], ['unknown', '未知类型'], ['no_current', '暂无报告']].map(([value, label]) => ({ value, label }))} /></Col>
        <Col xs={24} md={6}><label className="filter-label">最近执行状态</label><Select aria-label="最近执行状态" allowClear value={parsed.filters.latest_status} onChange={value => update({ latest_status: value })} style={{ width: '100%' }} options={LATEST_STATUSES.map(value => ({ value, label: value }))} /></Col>
        <Col xs={24} md={6}><label className="filter-label">分组</label><Select aria-label="分组" allowClear value={parsed.filters.grouping} onChange={value => update({ grouping: value })} style={{ width: '100%' }} options={[['exact', '已精确分组'], ['unclassified', '未分组']].map(([value, label]) => ({ value, label }))} /></Col>
        <Col xs={24} md={6}><label className="filter-label">版本状态</label><Select aria-label="版本状态" value={parsed.filters.version_unset ? 'unset' : 'all'} onChange={value => update({ version_unset: value === 'unset' || undefined, version: undefined })} style={{ width: '100%' }} options={[{ label: '全部版本', value: 'all' }, { label: '未声明版本', value: 'unset' }]} /></Col>
        <Col xs={12} md={6}><label className="filter-label" htmlFor="inbox-test-label">测试版本（人工）</label><Input id="inbox-test-label" value={draft.test_label} onChange={event => setDraft(value => ({ ...value, test_label: event.target.value }))} maxLength={200} /></Col>
        <Col xs={12} md={6}><label className="filter-label" htmlFor="inbox-test-batch">测试批次（人工）</label><Input id="inbox-test-batch" value={draft.test_batch} onChange={event => setDraft(value => ({ ...value, test_batch: event.target.value }))} maxLength={200} /></Col>
      </Row> }]} />
    </Card>

    {query.isLoading && !query.data ? <Card><LoadingState rows={8} /></Card> : query.isError && !query.data ? <Card><ErrorState description={errorDescription('Crash Inbox 加载失败', requestError)} onRetry={() => void query.refetch()} /></Card> : query.data ? <Card className="section-card" title={<Space>崩溃记录 <Tag>{query.data.items.length}</Tag>{query.isFetching && <Tag color="processing">后台刷新</Tag>}</Space>}>
      {query.isError && <Alert className="page-alert" type="warning" showIcon message="后台刷新失败，已保留现有列表" description={errorDescription('可稍后重试', requestError)} />}
      {!query.data.items.length ? filterCount ? <EmptyState description="当前筛选无结果" action={<Button onClick={clear}>清除筛选</Button>} /> : <EmptyState description="这个空间尚未上传 DMP" action={<LinkButton to={routePaths.upload(workspace.id)} type="primary">上传第一份 DMP</LinkButton>} /> : <OccurrenceSummaryTable workspaceId={workspace.id} items={query.data.items} />}
      <div className="inbox-pagination"><Button icon={<LeftOutlined />} disabled={!pagination.hasPrevious} onClick={pagination.previous}>上一页</Button><Text type="secondary">按发生时间从新到旧</Text><Button icon={<RightOutlined />} iconPosition="end" disabled={!query.data.next_cursor} onClick={() => query.data?.next_cursor && pagination.next(query.data.next_cursor)}>下一页</Button></div>
    </Card> : null}
  </div>
}

function textDraft(filters: OccurrenceListParams) {
  return { q: filters.q ?? '', version: filters.version ?? '', test_label: filters.test_label ?? '', test_batch: filters.test_batch ?? '', from: isoToLocalDateTime(filters.from), to: isoToLocalDateTime(filters.to) }
}

function isoToLocalDateTime(value: string | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function localDateTimeToIso(value: string): string | undefined {
  if (!value) return undefined
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? undefined : parsed.toISOString()
}

function errorDescription(prefix: string, error: CrashCapApiError | null) {
  if (!error) return prefix
  return <span>{prefix}（{error.code ?? error.status}）{error.requestId ? <><br />Request ID: <Text code>{error.requestId}</Text></> : null}</span>
}
