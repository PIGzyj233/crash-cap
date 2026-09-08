import { LinkButton } from '../components/LinkButton'
import { ArrowLeftOutlined,CopyOutlined,DownloadOutlined,DownOutlined,InfoCircleOutlined,ReloadOutlined,SearchOutlined,UpOutlined } from '@ant-design/icons'
import { Alert,App as AntApp,Button,Card,Collapse,Descriptions,Input,Result,Segmented,Space,Spin,Tabs,Tag,Tooltip,Typography } from 'antd'
import { useEffect,useMemo,useState,type Key } from 'react'
import { Link,useSearchParams } from 'react-router-dom'
import { CrashCapApiError } from '../api/client'
import { useApi } from '../api/context'
import { useCapabilities,useDeclareModuleRole,useModules,useOccurrence,useOccurrenceAnalysis,useOccurrenceProgress,useReprocessOccurrence,useThreads } from '../api/hooks'
import { isTerminalStatus,statusLabel } from '../api/polling'
import { useAnalysisDemand } from '../api/useAnalysisDemand'
import { AnalysisDemandStatus } from '../components/AnalysisDemandStatus'
import { AnalysisHistory } from '../components/AnalysisHistory'
import { ExecutionDetails,executionError,executionStage } from '../components/AnalysisExecution'
import { PublicSymbolFill } from '../components/PublicSymbolFill'
import { DataTable } from '../components/DataTable'
import { DemandRestartForm } from '../components/DemandRestartForm'
import { FRAME_ROW_KEY,frameColumns,moduleBasename,withFrameKeys,type KeyedFrame } from '../components/frameColumns'
import { ModuleSymbolSelection } from '../components/ModuleSymbolSelection'
import { OccurrenceVersionEditor } from '../components/OccurrenceVersionEditor'
import { SubmissionHistory } from '../components/SubmissionHistory'
import { ErrorState,HashValue,PageTitle,qualityGrade,QualityScore,StatusTag,WarningList } from '../components/ui'
import { routePaths } from '../routes/routePaths'
import { lastList } from '../routes/listNavigation'
import type { AnalysisModule,CanonicalReport,OccurrenceDetail,QualityWarning,StackFrame,Thread,Workspace } from '../types'

const { Text } = Typography
const REPORT_TABS = new Set(['diagnosis', 'threads', 'modules', 'history', 'metadata'])
const LEGACY_TABS: Record<string, string> = { overview: 'diagnosis', stack: 'diagnosis', raw: 'metadata', similar: 'diagnosis' }

function frameSearchText(frame: StackFrame) { return `${frame.module ?? ''} ${frame.function ?? ''} ${frame.file ?? ''}`.toLowerCase() }

function formatFunctionOffset(value: number | null | undefined) { return value == null ? '—' : `0x${value.toString(16)}` }

function FrameDetails({ frame }: { frame: StackFrame }) {
  return <div className="frame-details"><Descriptions size="small" column={{ xs: 1, sm: 2 }}>
    <Descriptions.Item label="绝对地址"><HashValue value={frame.instruction_addr} /></Descriptions.Item><Descriptions.Item label="相对地址"><HashValue value={frame.relative_addr} /></Descriptions.Item><Descriptions.Item label="module_debug_id"><HashValue value={frame.module_debug_id} length={24} /></Descriptions.Item><Descriptions.Item label="函数偏移">{formatFunctionOffset(frame.function_offset)}</Descriptions.Item><Descriptions.Item label="inline">{frame.inline ? <Tag color="purple">inline</Tag> : '否'}</Descriptions.Item><Descriptions.Item label="in_app">{frame.in_app ? <Tag color="blue">业务帧</Tag> : <Tag>系统帧</Tag>}</Descriptions.Item>
  </Descriptions>{frame.source_context && <Card size="small" title={frame.file ? `${frame.file}:${frame.line ?? '—'}` : 'Source context'}><pre className="json-block">{[...(frame.source_context.pre ?? []).map((line) => `  ${line}`), `> ${frame.source_context.line ?? ''}`, ...(frame.source_context.post ?? []).map((line) => `  ${line}`)].join('\n')}</pre></Card>}<Button size="small" onClick={() => navigator.clipboard?.writeText(`${frame.module ?? '?'}!${frame.function ?? '?'}+${formatFunctionOffset(frame.function_offset)}`)}>复制 WinDbg 风格栈</Button></div>
}

function stackLocation(frame: StackFrame | undefined) {
  if (!frame) return '未知故障位置'
  const module = moduleBasename(frame.module) ?? '未知模块'
  const method = frame.function ?? frame.function_normalized ?? '未符号化'
  return `${module}!${method}`
}

function processName(analysis: CanonicalReport) {
  const entrypoint = analysis.modules.find((module) => module.role === 'entrypoint')?.code_file
  const executable = analysis.modules.find((module) => /\.exe$/i.test(module.code_file))?.code_file
  return moduleBasename(entrypoint ?? executable) ?? '未知进程'
}

function CrashContextSummary({ analysis, frames, thread }: { analysis: CanonicalReport; frames: StackFrame[]; thread?: Thread }) {
  const first = frames[0]
  const location = stackLocation(first)
  const copyLocation = () => void navigator.clipboard?.writeText(`${location}${first?.function_offset == null ? '' : `+0x${first.function_offset.toString(16)}`}`)
  return <div className="crash-context-summary">
    <div className="crash-context-main">
      <div className="crash-context-item"><Text className="crash-context-label">进程</Text><Text strong className="crash-context-value">{processName(analysis)}</Text></div>
      <div className="crash-context-item crash-context-fault"><Text className="crash-context-label">故障位置</Text><Tooltip title={first?.module ?? '未知模块'}><Text strong className="crash-context-value cc-symbol">{location}</Text></Tooltip><Text type="secondary" className="crash-context-address">{first?.instruction_addr ?? '—'}</Text></div>
      <div className="crash-context-item"><Text className="crash-context-label">线程</Text><Text strong className="crash-context-value">{thread ? `Thread ${thread.id}` : '未知线程'}{thread?.name ? ` · ${thread.name}` : ''}</Text></div>
    </div>
    <Tooltip title="复制故障位置"><Button aria-label="复制故障位置" icon={<CopyOutlined />} onClick={copyLocation}>复制</Button></Tooltip>
  </div>
}

function StackTable({ frames, analysis, thread }: { frames: StackFrame[]; analysis?: CanonicalReport; thread?: Thread }) {
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<'all' | 'app'>('all')
  const [expanded, setExpanded] = useState<Key[]>([])
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    return frames.filter((frame) => (scope === 'all' || frame.in_app) && (!query || frameSearchText(frame).includes(query)))
  }, [frames, scope, search])
  const rows = useMemo(() => withFrameKeys(filtered), [filtered])
  const keys = useMemo(() => rows.map((frame) => frame.frameRowKey), [rows])
  const allExpanded = keys.length > 0 && expanded.length === keys.length
  return <div>
    {analysis && <CrashContextSummary analysis={analysis} frames={frames} thread={thread} />}
    <div className="stack-toolbar">
      <Input prefix={<SearchOutlined />} allowClear value={search} onChange={(event) => setSearch(event.target.value)} placeholder="按函数、模块或源码搜索" />
      <Segmented value={scope} onChange={(value) => setScope(value as 'all' | 'app')} options={[{ label: '全部帧', value: 'all' }, { label: '业务帧', value: 'app' }]} />
      <Text type="secondary" className="stack-count">{filtered.length} / {frames.length} 帧</Text>
      <Button size="small" icon={allExpanded ? <UpOutlined /> : <DownOutlined />} onClick={() => setExpanded(allExpanded ? [] : keys)}>{allExpanded ? '收起全部' : '展开全部'}</Button>
    </div>
    <DataTable<KeyedFrame<StackFrame>>
      rowKey={FRAME_ROW_KEY}
      dataSource={rows}
      minWidth={980}
      expandable={{ expandedRowKeys: expanded, onExpandedRowsChange: (keys) => setExpanded([...keys]), expandedRowRender: (row) => <FrameDetails frame={row} />, rowExpandable: () => true }}
      columns={frameColumns<KeyedFrame<StackFrame>>() }
    />
  </div>
}

function MetadataTab({ analysis, occurrence }: { analysis: CanonicalReport; occurrence: OccurrenceDetail }) {
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
  return <Space direction="vertical" size={18} style={{ width: '100%' }}>
    <Card title="DMP 与进程信息"><Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}><Descriptions.Item label="Blob"><HashValue value={analysis.dump.blob_id} /></Descriptions.Item><Descriptions.Item label="SHA-256"><HashValue value={analysis.dump.sha256} /></Descriptions.Item><Descriptions.Item label="Size">{(analysis.dump.size / 1024 / 1024).toFixed(1)} MiB</Descriptions.Item><Descriptions.Item label="Occurred at">{new Date(analysis.dump.occurred_at).toLocaleString('zh-CN')}</Descriptions.Item><Descriptions.Item label="PID">{analysis.process.pid ?? '—'}</Descriptions.Item><Descriptions.Item label="OS">{analysis.process.os} {analysis.process.os_version ?? ''}</Descriptions.Item></Descriptions></Card>
    <Card title="原始文件下载" extra={<Tooltip title="由部署级 RAW_DOWNLOAD_ENABLED 控制"><InfoCircleOutlined /></Tooltip>}><Space direction="vertical"><Text type="secondary">原始 DMP / PE / PDB 默认不向浏览器暴露 URL；报告摘要与 Canonical JSON 始终可查看。</Text>{api.rawDownloadEnabled && <Alert type="warning" showIcon message="已启用原始下载：Phase 1 无登录 / 权限过滤，仅限受信任内网使用。" description="预签名 URL 只短时有效，请勿复制到公网或第三方工单。" />}<Tooltip title={api.rawDownloadEnabled ? '下载短 TTL 预签名 URL' : 'RAW_DOWNLOAD_DISABLED'}><span><Button icon={<DownloadOutlined />} disabled={!api.rawDownloadEnabled} loading={downloadBusy} onClick={download}>{api.rawDownloadEnabled ? '下载原始 Dump' : '原始下载已禁用'}</Button></span></Tooltip>{!api.rawDownloadEnabled && <Tag color="orange">RAW_DOWNLOAD_DISABLED</Tag>}</Space></Card>
  </Space>
}

function ThreadsTab({ threads }: { threads: Thread[] }) {
  return <Collapse items={threads.map((thread) => ({ key: thread.id, label: <span>Thread {thread.id} {thread.is_crashing && <Tag color="red">crashed</Tag>} {thread.name && <Text type="secondary">· {thread.name}</Text>}</span>, children: <StackTable frames={thread.frames} />}))} />
}

function ModulesTab({ modules, warnings, workspaceId, occurrenceId, architecture }: { modules: AnalysisModule[]; warnings: QualityWarning[]; workspaceId: string; occurrenceId: string; architecture: string }) {
  const { message } = AntApp.useApp()
  const capabilities = useCapabilities()
  const declaration = useDeclareModuleRole(workspaceId, occurrenceId)
  const enabled = capabilities.data?.enabled_writes.includes('workspace_module_roles') === true
  const effectiveStatus = (module: AnalysisModule) => {
    if (module.status !== 'system_symbol_pending') return <StatusTag status={module.status} />
    if (module.source_outcomes.some(outcome => outcome.reason === 'source_budget_exhausted_before_request')) return <Tag color="orange">公共符号尚未请求</Tag>
    if (module.source_outcomes.some(outcome => outcome.stage === 'symbolicate' && outcome.failure_class === 'transient')) return <Tag color="orange">公共符号查询暂未完成</Tag>
    const warning = warnings.find((candidate) => candidate.module?.toLowerCase() === module.code_file?.toLowerCase() && candidate.code.startsWith('system_symbol_'))
    if (warning?.code === 'system_symbol_failed') return <StatusTag status="system_symbol_failed" />
    if (warning?.code === 'system_symbol_pending') return <StatusTag status="system_symbol_pending" />
    return <StatusTag status="system_symbol_pending" />
  }
  const declare = (module: AnalysisModule, role: 'owned' | 'dependency') => {
    if (!module.code_id || !module.debug_id || architecture !== 'x86_64') return
    declaration.mutate(
      { identity: { code_id: module.code_id, debug_id: module.debug_id, architecture }, role },
      {
        onSuccess: (result) => message.success(result.changed ? '角色声明已提交；新分析会采用该声明，当前历史报告保持不变。' : '该角色声明已存在。'),
        onError: (error) => message.error(error instanceof Error ? error.message : '角色声明失败'),
      },
    )
  }
  return <Space direction="vertical" size={12} style={{ width: '100%' }}>
    {modules.some((module) => module.role === 'unknown') && <Alert type="info" showIcon message="部分模块归属未声明（unknown）" description="符号匹配与业务归属分别判断。matched 表示该次分析已匹配符号；unknown 模块可显示函数和行号，但不会计入业务覆盖或作为业务帧。角色声明仅影响本 Workspace 的新分析。" />}
    {!enabled && <Alert type="info" showIcon message="精确模块角色声明当前未启用" description="报告仍展示已冻结的模块角色；部署通过资格门禁后才开放写入。" />}
    <DataTable<AnalysisModule> rowKey={row => `${row.code_file ?? 'unknown'}-${row.debug_id ?? 'none'}`} dataSource={modules} minWidth={640} expandable={{ expandedRowRender: row => <Space direction="vertical" style={{ width: '100%' }}><Descriptions size="small" column={{ xs: 1, md: 2 }}><Descriptions.Item label="Code ID"><HashValue value={row.code_id} length={64} /></Descriptions.Item><Descriptions.Item label="Debug ID"><HashValue value={row.debug_id} length={64} /></Descriptions.Item><Descriptions.Item label="文件引用">{row.artifact_ids.length ? row.artifact_ids.join(', ') : '无'}</Descriptions.Item></Descriptions><ModuleSymbolSelection selection={row.selection} outcomes={row.source_outcomes} /></Space> }} columns={[
      { title: '模块', dataIndex: 'code_file', render: (value: string | null, row) => <span><Text strong>{value ?? '—'}</Text><br /><Text type="secondary">{row.debug_file ?? '—'}</Text></span> },
      { title: '业务归属', dataIndex: 'role', width: 100, render: (value: string) => <Tag color={value === 'owned' ? 'blue' : undefined}>{value}</Tag> },
      { title: '该次分析的符号状态', width: 170, render: (_value, row) => effectiveStatus(row) },
      { title: '本空间归属声明', width: 195, render: (_value, row) => row.role === 'unknown' && row.code_id && row.debug_id && architecture === 'x86_64' ? <Space size={4}><Button size="small" disabled={!enabled} loading={declaration.isPending} onClick={() => declare(row, 'owned')} aria-label={`声明 ${row.code_file ?? '模块'} 为 owned`}>业务模块</Button><Button size="small" disabled={!enabled} loading={declaration.isPending} onClick={() => declare(row, 'dependency')} aria-label={`声明 ${row.code_file ?? '模块'} 为 dependency`}>依赖模块</Button></Space> : <Text type="secondary">{row.role === 'unknown' ? '捕获身份不完整' : '已有分类'}</Text> },
    ]} />
  </Space>
}

export function OccurrenceReport({ workspace, occurrenceId, onBack, onOpenGroup }: { workspace: Workspace; occurrenceId: string; onBack: () => void; onOpenGroup: (groupId: string) => void }) {
  void onBack
  void onOpenGroup
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab')
  const activeTab = requestedTab && (REPORT_TABS.has(requestedTab) ? requestedTab : LEGACY_TABS[requestedTab]) || 'diagnosis'
  const requestedRun = searchParams.get('run')?.trim() || undefined
  const progressMode = useOccurrenceProgress(occurrenceId)
  const { data: occurrence, error: occurrenceError, isLoading, isError, refetch } = useOccurrence(occurrenceId, progressMode !== 'sse')
  const demand = useAnalysisDemand(workspace.id, occurrenceId, occurrence?.workspace_id === workspace.id)
  const demandStatus = <>{requestedRun && occurrence && requestedRun !== occurrence.current_analysis?.id && <Alert type="info" showIcon message="正在查看历史分析报告" description={`报告 ${requestedRun} 保留该次分析结果。下方更新状态描述当前事故。`} action={<Link to={routePaths.occurrence(workspace.id, occurrenceId)}>返回当前报告</Link>} />}{demand.isError
    ? <Alert type="warning" showIcon message="分析更新状态暂时无法读取" action={<Button onClick={() => void demand.refetch()}>重试读取</Button>} />
    : <AnalysisDemandStatus compact demand={demand.data ?? null} reportStatus={occurrence?.current_analysis?.status} progress={occurrence?.latest_attempt?.progress} />}<DemandRestartForm key={`restart/${workspace.id}/${occurrenceId}/${demand.data?.generation ?? 0}`} workspaceId={workspace.id} occurrenceId={occurrenceId} demand={demand.data ?? null} onSaved={() => { void demand.refetch() }} /></>
  const selectedAttempt = requestedRun
    ? [occurrence?.current_analysis, occurrence?.latest_attempt].find((run) => run?.id === requestedRun)
    : occurrence?.current_analysis ?? occurrence?.latest_attempt
  const current = selectedAttempt
  const terminal = requestedRun && !selectedAttempt ? true : isTerminalStatus(current?.status)
  const successful = requestedRun && !selectedAttempt ? true : current?.status === 'COMPLETE' || current?.status === 'PARTIAL'
  const runId = requestedRun ?? occurrence?.current_analysis?.id ?? current?.id
  const { data: fetchedAnalysis, isError: analysisError, error: analysisLoadError, refetch: refetchAnalysis } = useOccurrenceAnalysis(occurrenceId, runId, Boolean(runId && successful))
  const { data: fetchedThreads } = useThreads(occurrenceId, activeTab === 'threads' && successful, runId)
  const { data: fetchedModules } = useModules(occurrenceId, activeTab === 'modules' && successful, runId)
  const reprocess = useReprocessOccurrence(occurrenceId)
  const analysis = fetchedAnalysis

  useEffect(() => {
    const next = new URLSearchParams(searchParams)
    let changed = false
    if (requestedTab && !REPORT_TABS.has(requestedTab)) {
      const replacement = LEGACY_TABS[requestedTab]
      if (replacement && replacement !== 'diagnosis') next.set('tab', replacement); else next.delete('tab')
      changed = true
    }
    if (searchParams.has('run') && !requestedRun) { next.delete('run'); changed = true }
    if (changed) setSearchParams(next, { replace: true })
  }, [requestedRun, requestedTab, searchParams, setSearchParams])

  if (isLoading) return <div className="center-state"><Spin size="large" /><Text type="secondary">正在读取 Occurrence…</Text></div>
  if (isError || !occurrence) {
    if (occurrenceError instanceof CrashCapApiError && occurrenceError.status === 404) {
      return <Result status="404" title="Occurrence 不存在" subTitle={`未找到 ${occurrenceId}，或该资源已被清理。`} extra={<Space><LinkButton to={lastList(routePaths.occurrences(workspace.id))} type="primary">返回崩溃记录</LinkButton><LinkButton to={routePaths.home}>返回平台主页</LinkButton></Space>} />
    }
    const requestId = occurrenceError instanceof CrashCapApiError ? occurrenceError.requestId : undefined
    return <ErrorState description={`Occurrence 加载失败${requestId ? ` · Request ID ${requestId}` : ''}`} onRetry={() => void refetch()} />
  }
  if (occurrence.workspace_id !== workspace.id) return <Result status="404" title="Occurrence 不属于当前 Workspace" subTitle={`URL Workspace=${workspace.id}，资源声明 Workspace=${occurrence.workspace_id}。平台不会静默切换或展示跨 Workspace 报告。`} extra={<Space><LinkButton to={lastList(routePaths.occurrences(workspace.id))} type="primary">返回当前 Crash Inbox</LinkButton><LinkButton to={routePaths.home}>返回平台主页</LinkButton></Space>} />
  const publicSymbols = <PublicSymbolFill key={`public/${workspace.id}/${occurrenceId}`} workspaceId={workspace.id} occurrenceId={occurrenceId} />
  const pendingHeader = <><Link className="back-button" to={lastList(routePaths.occurrences(workspace.id))}><ArrowLeftOutlined /> 返回崩溃记录</Link><PageTitle kicker="CRASH REPORT" title="崩溃报告" description={occurrence.id} extra={<OccurrenceVersionEditor occurrence={occurrence} />} />{demandStatus}{publicSymbols}</>
  const historyPanels = <Space direction="vertical" size="middle" style={{ width: '100%', marginTop: 20 }}><SubmissionHistory workspaceId={workspace.id} occurrenceId={occurrence.id} /><AnalysisHistory workspaceId={workspace.id} occurrenceId={occurrence.id} /></Space>
  if (terminal && !successful) {
    const stagingFailure = current?.error_code?.startsWith('CORE_STAGE_')
    return <div>{pendingHeader}<Card className="analysis-progress-card"><Alert type="error" showIcon message={stagingFailure ? '分析输入准备失败' : `分析${statusLabel(current?.status)}`} description={current ? executionError(current) : '分析未生成可展示结果'} /><Space wrap><StatusTag status={current?.status ?? 'FAILED'} /><HashValue value={current?.id} />{!demand.data && <Button type="primary" icon={<ReloadOutlined />} disabled={demand.isPending || demand.isError} loading={reprocess.isPending} onClick={() => reprocess.mutate()}>重新分析</Button>}</Space>{current && <ExecutionDetails run={current} />}<Text type="secondary">{demand.data ? '自动重试耗尽后可请求重新分析，说明可选。原失败记录会保留在历史中。' : '重新分析会创建新的 Analysis Run，原失败 Run 会保留作为历史证据。'}</Text></Card>{historyPanels}</div>
  }
  if (analysisError) return <div>{pendingHeader}<Card><ErrorState description={analysisLoadError instanceof CrashCapApiError && analysisLoadError.code === 'CANONICAL_VERSION_UNSUPPORTED' ? analysisLoadError.message : `Analysis Run ${runId ?? '—'} 无法加载；请确认它属于当前 Occurrence 且有可用结果。`} onRetry={() => void refetchAnalysis()} /></Card>{historyPanels}</div>
  if (!analysis || !terminal) return <div>{pendingHeader}<Card className="analysis-progress-card"><Spin /><Typography.Title level={3}>{statusLabel(current?.status)}</Typography.Title><Text type="secondary">{executionStage(current?.progress) ?? '正在处理这份 DMP，分析状态会自动更新。'}</Text><div className="progress-status"><StatusTag status={current?.status ?? 'UPLOADED'} /><HashValue value={current?.id} /></div></Card>{historyPanels}</div>

  const result = analysis
  const threads = fetchedThreads ?? result.threads
  const modules = fetchedModules ?? result.modules
  const tabItems = [
    { key: 'diagnosis', label: '诊断', children: <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <div className="diagnosis-summary"><Space wrap><Tag>{result.crash.type}</Tag><Text>{result.crash.access_type ?? '未知访问类型'} · {result.crash.address ?? '—'}</Text>{occurrence.group ? <Link to={routePaths.group(workspace.id, occurrence.group.id)}>相同崩溃分组：{occurrence.group.title}</Link> : <Text type="secondary">尚未精确分组</Text>}</Space><Button icon={<ReloadOutlined />} loading={reprocess.isPending} onClick={() => reprocess.mutate()}>重新分析</Button></div>
      {reprocess.isError && <Alert type="error" message={reprocess.error.message} />}
      <Card title={<span>崩溃线程 · Thread {result.crash.thread_id ?? '—'}</span>} style={{ width: '100%' }}><StackTable analysis={result} thread={threads.find(thread => thread.id === result.crash.thread_id)} frames={threads.find(thread => thread.id === result.crash.thread_id)?.frames ?? []} /></Card>
      <Collapse style={{ width: '100%' }} items={[{ key: 'quality', label: `分析质量与限制 · ${result.quality.warnings.length} 条提示`, children: <><QualityScore score={result.quality.score} /><WarningList warnings={result.quality.warnings} /></> }]} />
    </Space> },
    { key: 'threads', label: '全部线程', children: <Card><ThreadsTab threads={threads} /></Card> },
    { key: 'modules', label: '模块与符号', children: <Card><Space direction="vertical" size="middle" style={{ width: '100%' }}><Link to={routePaths.symbols(workspace.id)}>在符号中心查看当前问题与补传文件</Link><ModulesTab modules={modules} warnings={result.quality.warnings} workspaceId={workspace.id} occurrenceId={occurrence.id} architecture={result.process.architecture} /></Space></Card> },
    { key: 'history', label: '历史与复核', children: <Space direction="vertical" size="middle" style={{ width: '100%' }}><SubmissionHistory key={`${workspace.id}/${occurrenceId}`} workspaceId={workspace.id} occurrenceId={occurrenceId} /><AnalysisHistory key={`runs/${workspace.id}/${occurrenceId}`} workspaceId={workspace.id} occurrenceId={occurrenceId} /></Space> },
    { key: 'metadata', label: '元数据', children: <Space direction="vertical" size="middle" style={{ width: '100%' }}><MetadataTab analysis={result} occurrence={occurrence} /><Card title="报告元数据"><pre className="json-block">{JSON.stringify({ dump: result.dump, process: result.process, engine: result.engine }, null, 2)}</pre><Text type="secondary">此处是分析报告元数据，不是原始内存转储。</Text></Card></Space> },
  ]

  const currentRun = occurrence.current_analysis
  const latestRun = occurrence.latest_attempt
  const reportPath = routePaths.occurrence(workspace.id, occurrence.id)
  return <div>
    <Link className="back-button" to={lastList(routePaths.occurrences(workspace.id))}><ArrowLeftOutlined /> 返回崩溃记录</Link>
    <PageTitle kicker="CRASH REPORT" title={`${result.crash.exception_name ?? result.crash.exception_code ?? 'Unknown'} · ${result.crash.access_type ?? 'access'}`} description={`${result.crash.fault_module ?? 'unknown module'} · ${result.process.architecture} · 报告质量 ${qualityGrade(result.quality.score)} ${Math.round(result.quality.score * 100)}%`} extra={<OccurrenceVersionEditor occurrence={occurrence} />} />
    <Space wrap className="report-selection">{current && <StatusTag status={current.status} />}{currentRun && <Link to={`${reportPath}${reportSearch(activeTab, currentRun.id)}`}>当前采用报告</Link>}{latestRun && latestRun.id !== currentRun?.id && <Link to={`${reportPath}${reportSearch(activeTab, latestRun.id)}`}>最近一次尝试</Link>}<Text type="secondary">{occurrence.id}</Text></Space>
    {demandStatus}
    {publicSymbols}
    <Tabs activeKey={activeTab} onChange={key => { const next = new URLSearchParams(searchParams); if (key === 'diagnosis') next.delete('tab'); else next.set('tab', key); setSearchParams(next, { replace: false }) }} items={tabItems} destroyOnHidden={false} />
    <div className="report-footnote"><InfoCircleOutlined /> 报告 {runId} · Core {result.engine.core_version} · Symbolicator {result.engine.symbolicator_version}</div>
  </div>
}

function reportSearch(tab: string, runId: string): string {
  const query = new URLSearchParams()
  if (tab !== 'diagnosis') query.set('tab', tab)
  query.set('run', runId)
  return `?${query.toString()}`
}
