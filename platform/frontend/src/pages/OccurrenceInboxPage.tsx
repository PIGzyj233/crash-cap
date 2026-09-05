import { ClearOutlined,CloudUploadOutlined,LeftOutlined,ReloadOutlined,RightOutlined,SearchOutlined } from '@ant-design/icons'
import { Alert,Button,Card,Col,Input,Row,Select,Space,Tag,Typography } from 'antd'
import { useEffect,useMemo,useState } from 'react'
import { Link,useNavigate,useSearchParams } from 'react-router-dom'
import { CrashCapApiError } from '../api/client'
import { useOccurrences } from '../api/hooks'
import { OccurrenceSummaryTable } from '../components/OccurrenceSummary'
import { EmptyState,ErrorState,LoadingState,PageTitle } from '../components/ui'
import { useWorkspaceRoute } from '../layouts/WorkspaceLayout'
import { parseInboxQuery,serializeInboxQuery } from '../routes/inboxQuery'
import { routePaths } from '../routes/routePaths'
import type { OccurrenceListParams } from '../types'

const { Text } = Typography
const LATEST_STATUSES = ['UPLOADED', 'VALIDATING', 'INSPECTED', 'MATCHING_SYMBOLS', 'WAITING_FOR_SYMBOLS', 'SYMBOLS_READY', 'QUEUED', 'ANALYZING', 'NORMALIZING', 'GROUPING', 'COMPLETE', 'PARTIAL', 'FAILED', 'REJECTED', 'CANCELLED', 'TIMEOUT', 'OOM']

export function OccurrenceInboxPage() {
  const workspace = useWorkspaceRoute()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
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
    test_label: draft.test_label || undefined,
    test_batch: draft.test_batch || undefined,
    from: localDateTimeToIso(draft.from),
    to: localDateTimeToIso(draft.to),
  })
  const clear = () => setSearchParams(new URLSearchParams(), { replace: true })
  const filterCount = Object.entries(parsed.filters).filter(([key, value]) => key !== 'cursor' && value !== undefined).length
  const requestError = query.error instanceof CrashCapApiError ? query.error : null

  return <div>
    <PageTitle kicker={`${workspace.display_name ?? workspace.name} / CRASH INBOX`} title="Crash Inbox" description="按发生时间倒序浏览全部 Occurrence；Current Analysis 与 latest attempt 始终独立展示。" extra={<Space><Tag color="blue">{filterCount} 个筛选</Tag><Link to={routePaths.upload(workspace.id)}><Button type="primary" icon={<CloudUploadOutlined />}>上传 Dump</Button></Link></Space>} />
    <Card className="section-card inbox-filters" title="筛选与搜索" extra={<Space><Button icon={<ClearOutlined />} onClick={clear} disabled={!filterCount && !parsed.filters.cursor}>清除筛选</Button><Button type="primary" icon={<SearchOutlined />} onClick={applyText}>应用</Button></Space>}>
      <Row gutter={[12, 12]}>
        <Col xs={24} md={8}><label className="filter-label" htmlFor="inbox-q">文本搜索</label><Input id="inbox-q" value={draft.q} onChange={(event) => setDraft((value) => ({ ...value, q: event.target.value }))} onPressEnter={applyText} maxLength={128} placeholder="Occurrence / 异常 / 模块 / 函数 / Version" allowClear /></Col>
        <Col xs={12} md={4}><label className="filter-label">Crash type</label><Select aria-label="Crash type" allowClear value={parsed.filters.crash_type} onChange={(value) => update({ crash_type: value })} style={{ width: '100%' }} options={[['crash', 'Crash'], ['hang', 'Hang'], ['unknown', 'Unknown'], ['no_current', 'No Current']].map(([value, label]) => ({ value, label }))} /></Col>
        <Col xs={12} md={4}><label className="filter-label">Latest status</label><Select aria-label="Latest status" allowClear value={parsed.filters.latest_status} onChange={(value) => update({ latest_status: value })} style={{ width: '100%' }} options={LATEST_STATUSES.map((value) => ({ value, label: value }))} /></Col>
        <Col xs={12} md={4}><label className="filter-label">Grouping</label><Select aria-label="Grouping" allowClear value={parsed.filters.grouping} onChange={(value) => update({ grouping: value })} style={{ width: '100%' }} options={[['exact', 'Exact'], ['unclassified', 'Unclassified'], ['no_current', 'No Current']].map(([value, label]) => ({ value, label }))} /></Col>
        <Col xs={12} md={5}><label className="filter-label" htmlFor="inbox-from">From</label><Input id="inbox-from" type="datetime-local" value={draft.from} onChange={(event) => setDraft((value) => ({ ...value, from: event.target.value }))} /></Col>
        <Col xs={12} md={5}><label className="filter-label" htmlFor="inbox-to">To</label><Input id="inbox-to" type="datetime-local" value={draft.to} onChange={(event) => setDraft((value) => ({ ...value, to: event.target.value }))} /></Col>
        <Col xs={12} md={5}><label className="filter-label" htmlFor="inbox-version">Version</label><Input id="inbox-version" value={draft.version} onChange={(event) => setDraft((value) => ({ ...value, version: event.target.value }))} maxLength={200} placeholder="精确匹配" /></Col>
        <Col xs={24} md={4}><label className="filter-label">刷新</label><Button block icon={<ReloadOutlined />} loading={query.isFetching} onClick={() => void query.refetch()}>刷新当前页</Button></Col>
        <Col xs={12} md={6}><label className="filter-label" htmlFor="inbox-test-label">测试版本（人工）</label><Input id="inbox-test-label" value={draft.test_label} onChange={(event) => setDraft((value) => ({ ...value, test_label: event.target.value }))} maxLength={256} placeholder="精确匹配提交标注" /></Col>
        <Col xs={12} md={6}><label className="filter-label" htmlFor="inbox-test-batch">测试批次（人工）</label><Input id="inbox-test-batch" value={draft.test_batch} onChange={(event) => setDraft((value) => ({ ...value, test_batch: event.target.value }))} maxLength={256} placeholder="与版本匹配同一次提交" /></Col>
      </Row>
    </Card>

    {query.isLoading && !query.data ? <Card><LoadingState rows={8} /></Card> : query.isError && !query.data ? <Card><ErrorState description={errorDescription('Crash Inbox 加载失败', requestError)} onRetry={() => void query.refetch()} /></Card> : query.data ? <Card className="section-card" title={<Space>Occurrence <Tag>{query.data.items.length}</Tag>{query.isFetching && <Tag color="processing">后台刷新</Tag>}</Space>}>
      {query.isError && <Alert className="page-alert" type="warning" showIcon message="后台刷新失败，已保留现有列表" description={errorDescription('可稍后重试', requestError)} />}
      {!query.data.items.length ? filterCount ? <EmptyState description="当前筛选无结果" action={<Button onClick={clear}>清除筛选</Button>} /> : <EmptyState description="这个 Workspace 还没有 Occurrence" action={<Link to={routePaths.upload(workspace.id)}><Button type="primary">上传第一个 Dump</Button></Link>} /> : <OccurrenceSummaryTable workspaceId={workspace.id} items={query.data.items} />}
      <div className="inbox-pagination"><Button icon={<LeftOutlined />} disabled={!parsed.filters.cursor} onClick={() => navigate(-1)}>上一页（浏览器历史）</Button><Text type="secondary">固定排序 occurred_at DESC, id DESC</Text><Button icon={<RightOutlined />} iconPosition="end" disabled={!query.data.next_cursor} onClick={() => query.data?.next_cursor && setSearchParams(serializeInboxQuery({ ...parsed.filters, cursor: query.data.next_cursor }), { replace: false })}>下一页</Button></div>
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
