import { useMemo, useState } from 'react'
import { Alert, App as AntApp, Button, Card, Collapse, Descriptions, Empty, Input, List, Space, Spin, Statistic, Table, Tabs, Tag, Tooltip, Typography } from 'antd'
import { ArrowLeftOutlined, DownloadOutlined, InfoCircleOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { useApi } from '../api/context'
import { useModules, useOccurrence, useOccurrenceAnalysis, useOccurrenceProgress, useReprocessOccurrence, useThreads } from '../api/hooks'
import { isTerminalStatus, statusLabel } from '../api/polling'
import type { AnalysisModule, CanonicalReport, FrameTrust, OccurrenceDetail, StackFrame, Thread, Workspace } from '../types'
import { HashValue, PageTitle, QualityScore, StatusTag, TrustTag, WarningList } from '../components/ui'

const { Text, Paragraph } = Typography

function frameSearchText(frame: StackFrame) { return `${frame.module ?? ''} ${frame.function ?? ''} ${frame.file ?? ''}`.toLowerCase() }

function formatFunctionOffset(value: number | null | undefined) { return value == null ? '—' : `0x${value.toString(16)}` }

function FrameDetails({ frame }: { frame: StackFrame }) {
  return <div className="frame-details"><Descriptions size="small" column={{ xs: 1, sm: 2 }}>
    <Descriptions.Item label="绝对地址"><HashValue value={frame.instruction_addr} /></Descriptions.Item><Descriptions.Item label="相对地址"><HashValue value={frame.relative_addr} /></Descriptions.Item><Descriptions.Item label="module_debug_id"><HashValue value={frame.module_debug_id} length={24} /></Descriptions.Item><Descriptions.Item label="函数偏移">{formatFunctionOffset(frame.function_offset)}</Descriptions.Item><Descriptions.Item label="inline">{frame.inline ? <Tag color="purple">inline</Tag> : '否'}</Descriptions.Item><Descriptions.Item label="in_app">{frame.in_app ? <Tag color="blue">业务帧</Tag> : <Tag>系统帧</Tag>}</Descriptions.Item>
  </Descriptions>{frame.source_context && <Card size="small" title={frame.file ? `${frame.file}:${frame.line ?? '—'}` : 'Source context'}><pre className="json-block">{[...(frame.source_context.pre ?? []).map((line) => `  ${line}`), `> ${frame.source_context.line ?? ''}`, ...(frame.source_context.post ?? []).map((line) => `  ${line}`)].join('\n')}</pre></Card>}<Button size="small" onClick={() => navigator.clipboard?.writeText(`${frame.module ?? '?'}!${frame.function ?? '?'}+${formatFunctionOffset(frame.function_offset)}`)}>复制 WinDbg 风格栈</Button></div>
}

function StackTable({ frames }: { frames: StackFrame[] }) {
  const [search, setSearch] = useState('')
  const filtered = useMemo(() => { const query = search.trim().toLowerCase(); return query ? frames.filter((frame) => frameSearchText(frame).includes(query)) : frames }, [frames, search])
  return <div><Input prefix={<SearchOutlined />} allowClear value={search} onChange={(event) => setSearch(event.target.value)} placeholder="按函数、模块或源码搜索" style={{ maxWidth: 360, marginBottom: 12 }} /><Table rowKey={(row) => `${row.index}-${row.instruction_addr}`} size="small" pagination={false} dataSource={filtered} expandable={{ expandedRowRender: (row) => <FrameDetails frame={row} />, rowExpandable: () => true }} columns={[{ title: '#', dataIndex: 'index', width: 60 }, { title: 'Module', dataIndex: 'module', render: (value: string | null, row: StackFrame) => <span><Text strong>{value ?? '—'}</Text>{row.in_app && <Tag color="blue" className="frame-app-tag">app</Tag>}</span> }, { title: 'Function', dataIndex: 'function', render: (value: string | null, row: StackFrame) => <span>{value ?? <Text type="secondary">未符号化</Text>}{row.inline && <Tag color="purple" className="frame-app-tag">inline</Tag>}</span> }, { title: 'Source', key: 'source', render: (_, row: StackFrame) => row.file ? `${row.file}:${row.line ?? '—'}` : '—' }, { title: 'Trust', dataIndex: 'trust', render: (value: FrameTrust) => <TrustTag trust={value} /> }]} /></div>
}

function OverviewTab({ analysis, occurrence, onReprocess }: { analysis: CanonicalReport; occurrence: OccurrenceDetail; onReprocess: () => void }) {
  const api = useApi()
  const { message } = AntApp.useApp()
  const [downloadBusy, setDownloadBusy] = useState(false)
  const download = async () => {
    try {
      setDownloadBusy(true)
      const result = await api.getRawDownload(occurrence.id)
      window.open(result.url, '_blank', 'noopener,noreferrer')
    } catch (error) { message.error(error instanceof Error ? error.message : '原始下载被拒绝') } finally { setDownloadBusy(false) }
  }
  const resolution = analysis.build_resolution
  return <Space direction="vertical" size={18} style={{ width: '100%' }}>
    <Card className="report-hero" bordered={false}><div className="report-hero-main"><div className="exception-mark">!</div><div><div className="page-kicker">{analysis.crash.type.toUpperCase()} · {analysis.crash.access_type ?? 'unknown access'}</div><Typography.Title level={2}>{analysis.crash.exception_name ?? analysis.crash.exception_code ?? 'Unknown crash'}</Typography.Title><Text type="secondary">{analysis.crash.fault_module ?? 'unknown module'} · {analysis.crash.address ?? '—'} · {analysis.process.architecture}</Text></div></div><div className="report-hero-quality"><QualityScore score={analysis.quality.score} /><Button icon={<ReloadOutlined />} onClick={onReprocess}>Reprocess</Button></div></Card>
    <div className="metric-grid metric-grid-3"><Card><Statistic title="Crash type" value={analysis.crash.type} valueStyle={{ color: analysis.crash.type === 'crash' ? '#ff6b7a' : '#4e8cff' }} /><Text type="secondary">证据：{analysis.crash.type_evidence}</Text></Card><Card><Statistic title="Fault thread" value={analysis.crash.thread_id ?? '—'} /><Text type="secondary">{analysis.threads.find((thread) => thread.id === analysis.crash.thread_id)?.name ?? '未命名线程'}</Text></Card><Card><Statistic title="Exact" value={analysis.fingerprints.exact ? '已入组' : 'Unclassified'} /><Text type="secondary">{analysis.fingerprints.algorithm}</Text></Card></div>
    <Card title="Build resolution"><Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}><Descriptions.Item label="方法"><StatusTag status={resolution.resolution_method} /></Descriptions.Item><Descriptions.Item label="Resolved Build"><HashValue value={resolution.resolved_build_id} /></Descriptions.Item><Descriptions.Item label="Reported Build"><HashValue value={resolution.reported_build_id} /></Descriptions.Item><Descriptions.Item label="命中 entrypoint">{resolution.evidence.matched_entrypoints.join(', ') || '—'}</Descriptions.Item><Descriptions.Item label="命中 owned">{resolution.evidence.matched_owned_modules.join(', ') || '—'}</Descriptions.Item><Descriptions.Item label="冲突">{resolution.evidence.conflicting_modules.join(', ') || '无'}</Descriptions.Item></Descriptions></Card>
    <Card title="Quality warnings"><WarningList warnings={analysis.quality.warnings} /></Card>
    <Card title="Dump / Process metadata"><Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}><Descriptions.Item label="Blob"><HashValue value={analysis.dump.blob_id} /></Descriptions.Item><Descriptions.Item label="SHA-256"><HashValue value={analysis.dump.sha256} /></Descriptions.Item><Descriptions.Item label="Size">{(analysis.dump.size / 1024 / 1024).toFixed(1)} MiB</Descriptions.Item><Descriptions.Item label="Occurred at">{new Date(analysis.dump.occurred_at).toLocaleString('zh-CN')}</Descriptions.Item><Descriptions.Item label="PID">{analysis.process.pid ?? '—'}</Descriptions.Item><Descriptions.Item label="OS">{analysis.process.os} {analysis.process.os_version ?? ''}</Descriptions.Item></Descriptions></Card>
    <Card title="Raw Metadata 下载" extra={<Tooltip title="由部署级 RAW_DOWNLOAD_ENABLED 控制"><InfoCircleOutlined /></Tooltip>}><Space direction="vertical"><Text type="secondary">原始 DMP / PE / PDB 默认不向浏览器暴露 URL；报告摘要与 Canonical JSON 始终可查看。</Text>{api.rawDownloadEnabled && <Alert type="warning" showIcon message="已启用原始下载：Phase 1 无登录 / 权限过滤，仅限受信任内网使用。" description="预签名 URL 只短时有效，请勿复制到公网或第三方工单。" />}<Tooltip title={api.rawDownloadEnabled ? '下载短 TTL 预签名 URL' : 'RAW_DOWNLOAD_DISABLED'}><span><Button icon={<DownloadOutlined />} disabled={!api.rawDownloadEnabled} loading={downloadBusy} onClick={download}>{api.rawDownloadEnabled ? '下载原始 Dump' : '原始下载已禁用'}</Button></span></Tooltip>{!api.rawDownloadEnabled && <Tag color="orange">RAW_DOWNLOAD_DISABLED</Tag>}</Space></Card>
  </Space>
}

function ThreadsTab({ threads }: { threads: Thread[] }) {
  return <Collapse items={threads.map((thread) => ({ key: thread.id, label: <span>Thread {thread.id} {thread.is_crashing && <Tag color="red">crashed</Tag>} {thread.name && <Text type="secondary">· {thread.name}</Text>}</span>, children: <StackTable frames={thread.frames} />}))} />
}

function ModulesTab({ modules }: { modules: AnalysisModule[] }) {
  return <Table rowKey={(row) => `${row.code_file ?? 'unknown'}-${row.debug_id ?? 'none'}`} dataSource={modules} pagination={false} scroll={{ x: 880 }} columns={[{ title: 'Module', dataIndex: 'code_file', render: (value: string | null, row: AnalysisModule) => <span><Text strong>{value ?? '—'}</Text><br /><Text type="secondary">{row.debug_file ?? '—'}</Text></span> }, { title: 'Role', dataIndex: 'role', render: (value: string) => <Tag color={value === 'entrypoint' ? 'purple' : value === 'owned' ? 'blue' : 'default'}>{value}</Tag> }, { title: 'Status', dataIndex: 'status', render: (value: string) => <StatusTag status={value} /> }, { title: 'Code ID', dataIndex: 'code_id', render: (value: string | null) => <HashValue value={value} /> }, { title: 'Debug ID', dataIndex: 'debug_id', render: (value: string | null) => <HashValue value={value} /> }, { title: 'Artifacts', dataIndex: 'artifact_ids', render: (value: string[]) => value.length ? value.join(', ') : '—' }]} />
}

export function OccurrenceReport({ workspace, occurrenceId, onBack, onOpenGroup }: { workspace: Workspace; occurrenceId: string; onBack: () => void; onOpenGroup: (groupId: string) => void }) {
  const progressMode = useOccurrenceProgress(occurrenceId)
  const { data: occurrence, isLoading, isError, refetch } = useOccurrence(occurrenceId, progressMode !== 'sse')
  const [activeTab, setActiveTab] = useState('overview')
  const current = occurrence?.current_analysis ?? occurrence?.latest_attempt
  const terminal = isTerminalStatus(current?.status)
  const runId = occurrence?.current_analysis?.id ?? current?.id
  const { data: fetchedAnalysis } = useOccurrenceAnalysis(occurrenceId, runId, terminal)
  const { data: fetchedThreads } = useThreads(occurrenceId, activeTab === 'threads' && terminal, runId)
  const { data: fetchedModules } = useModules(occurrenceId, activeTab === 'modules' && terminal, runId)
  const reprocess = useReprocessOccurrence(occurrenceId)
  const analysis = fetchedAnalysis

  if (isLoading) return <div className="center-state"><Spin size="large" /><Text type="secondary">正在读取 Occurrence…</Text></div>
  if (isError || !occurrence) return <Empty description="Occurrence 加载失败"><Button onClick={() => refetch()}>重试</Button></Empty>
  if (!analysis || !terminal) return <div><Button type="link" icon={<ArrowLeftOutlined />} onClick={onBack}>返回 Workspace</Button><Card className="analysis-progress-card"><Spin /><Typography.Title level={3}>分析{statusLabel(current?.status)}</Typography.Title><Text type="secondary">SSE 实时推送任务进度；连接失败时自动回退到 2 秒 / 10 秒轮询，页面隐藏时暂停。</Text><div className="progress-status"><StatusTag status={current?.status ?? 'UPLOADED'} /><Tag color={progressMode === 'sse' ? 'green' : progressMode === 'connecting' ? 'blue' : 'orange'}>{progressMode === 'sse' ? 'SSE' : progressMode === 'connecting' ? 'SSE CONNECTING' : 'POLLING FALLBACK'}</Tag><HashValue value={current?.id} /></div></Card></div>

  const result = analysis
  const threads = fetchedThreads ?? result.threads
  const modules = fetchedModules ?? result.modules
  const tabItems = [
    { key: 'overview', label: 'Overview', children: <OverviewTab analysis={result} occurrence={occurrence} onReprocess={() => reprocess.mutate()} /> },
    { key: 'stack', label: 'Crash Stack', children: <Card title={<span>Thread {result.crash.thread_id ?? '—'} <Tag color="red">崩溃线程</Tag></span>}><StackTable frames={threads.find((thread) => thread.id === result.crash.thread_id)?.frames ?? []} /></Card> },
    { key: 'threads', label: 'All Threads', children: <Card><ThreadsTab threads={threads} /></Card> },
    { key: 'modules', label: 'Modules', children: <Card><ModulesTab modules={modules} /></Card> },
    { key: 'raw', label: 'Raw Metadata', children: <Card><pre className="json-block">{JSON.stringify({ dump: result.dump, process: result.process, build_resolution: result.build_resolution, engine: result.engine }, null, 2)}</pre><Alert type="info" showIcon message="此处是 Canonical metadata 摘要，不是原始内存转储。" /></Card> },
    { key: 'similar', label: 'Similar Crashes', children: <Card>{occurrence.group ? <Space direction="vertical"><Alert type="success" showIcon message="已匹配 Exact Group" description={occurrence.group.title} /><Button type="primary" onClick={() => onOpenGroup(occurrence.group!.id)}>查看 Group</Button></Space> : <Alert type="info" showIcon message="Unclassified" description="没有满足 Exact 前置条件；不会构造弱指纹或伪 Group。" />}</Card> },
  ]

  return <div><Button type="link" icon={<ArrowLeftOutlined />} onClick={onBack} className="back-button">返回 Workspace</Button><PageTitle kicker={`${workspace.display_name} / OCCURRENCE REPORT`} title={`${result.crash.exception_name ?? result.crash.exception_code ?? 'Unknown'} · ${result.crash.access_type ?? 'access'}`} description={`${result.crash.fault_module ?? 'unknown module'} · ${result.threads.find((thread) => thread.id === result.crash.thread_id)?.frames[0]?.function ?? '未符号化'} · ${result.process.architecture}`} extra={<Space><StatusTag status={current?.status ?? 'COMPLETE'} /><Tag color="geekblue">{occurrence.id}</Tag></Space>} /><Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} destroyInactiveTabPane={false} /><div className="report-footnote"><InfoCircleOutlined /> Canonical schema {result.schema_version} · Core {result.engine.core_version} · Symbolicator {result.engine.symbolicator_version} · 页面隐藏时轮询暂停</div></div>
}
