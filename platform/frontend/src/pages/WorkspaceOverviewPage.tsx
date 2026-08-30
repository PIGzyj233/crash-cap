import { useMemo, useState } from 'react'
import { Alert, App as AntApp, Button, Card, Col, Divider, List, Progress, Row, Select, Space, Statistic, Tag, Typography, Upload } from 'antd'
import { ArrowRightOutlined, CloudUploadOutlined, UploadOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { useApi } from '../api/context'
import { useBuilds, useWorkspaceOverview } from '../api/hooks'
import type { Build, CaptureProfile, Workspace } from '../types'
import { DataTable } from '../components/DataTable'
import { ErrorState, HashValue, LoadingState, MetricCard, PageTitle, QualityScore, StatusTag, UploadHint } from '../components/ui'
import { routePaths } from '../routes/routePaths'

const { Text } = Typography
const MAX_DUMP_SIZE = 256 * 1024 * 1024

function formatDuration(ms: number) {
  if (ms < 1_000) return `${ms} ms`
  return `${(ms / 1_000).toFixed(1)} s`
}

export function DumpUploadCard({ workspace, onOpenOccurrence }: { workspace: Workspace; onOpenOccurrence: (occurrenceId: string) => void }) {
  const api = useApi()
  const { message } = AntApp.useApp()
  const { data: builds } = useBuilds(workspace.id)
  const [file, setFile] = useState<File | null>(null)
  const [profile, setProfile] = useState<CaptureProfile>('rich-crash')
  const [reportedBuild, setReportedBuild] = useState<string>()
  const [progress, setProgress] = useState(0)
  const [state, setState] = useState<'idle' | 'uploading' | 'verifying' | 'done' | 'error'>('idle')

  const startUpload = async () => {
    if (!file) return message.warning('请先选择 .dmp 文件')
    if (file.size > MAX_DUMP_SIZE) return message.error('DMP 超过 256 MiB 上限，已拒绝')
    if (profile === 'full-memory') return message.error('Phase 1 不接受 full-memory Dump')
    try {
      setState('uploading')
      setProgress(0)
      const upload = await api.initDumpUpload(workspace.id, { filename: file.name, size: file.size, capture_profile: profile, reported_build_id: reportedBuild })
      const completion = await api.uploadPresigned(upload, file, setProgress)
      setState('verifying')
      const completed = await api.completeUpload(upload.upload_id, completion)
      const verified = await api.waitForUpload(upload.upload_id)
      const verificationStatus = (verified.status ?? verified.verification_status).toUpperCase()
      if (verificationStatus !== 'ACCEPTED') {
        throw new Error(`Dump 校验未通过：${verificationStatus}`)
      }
      setState('done')
      setProgress(100)
      const duplicate = verified.duplicate ?? completed.duplicate
      message.success(duplicate ? '内容已去重，复用已有 Occurrence' : 'Dump 已接收，分析任务已创建')
      if (verified.occurrence_id) onOpenOccurrence(verified.occurrence_id)
    } catch (error) {
      setState('error')
      message.error(error instanceof Error ? error.message : 'Dump 上传失败')
    }
  }

  return (
    <Card title={<span><CloudUploadOutlined /> 上传 Dump</span>} extra={<Tag color="blue">浏览器经 S3 Gateway 直传</Tag>} className="upload-card">
      <Space direction="vertical" size={14} style={{ width: '100%' }}>
        <Upload.Dragger accept=".dmp" maxCount={1} beforeUpload={(candidate) => { setFile(candidate); setState('idle'); return false }} onRemove={() => { setFile(null); setState('idle') }} showUploadList={Boolean(file)}>
          <p className="ant-upload-drag-icon"><UploadOutlined /></p>
          <p className="ant-upload-text">拖入 .dmp，或点击选择</p>
          <p className="ant-upload-hint">服务端会重新计算 SHA-256；同 Workspace 同内容只计一个 Occurrence。</p>
        </Upload.Dragger>
        <Row gutter={12}>
          <Col span={12}><Text type="secondary">采集剖面</Text><Select value={profile} onChange={setProfile} style={{ width: '100%', marginTop: 6 }} options={[{ value: 'light-crash', label: 'Light crash' }, { value: 'rich-crash', label: 'Rich crash' }, { value: 'hang', label: 'Hang（明确意图）' }]} /></Col>
          <Col span={12}><Text type="secondary">已知 Build（可选，高级）</Text><Select allowClear value={reportedBuild} onChange={setReportedBuild} style={{ width: '100%', marginTop: 6 }} placeholder="留空时按模块身份自动识别" options={(builds ?? []).map((build) => ({ value: build.id, label: `${build.version} · ${build.id}` }))} /></Col>
        </Row>
        {state === 'uploading' && <div><Text type="secondary">直传进度 {progress}%</Text><Progress percent={progress} status="active" /></div>}
        {state === 'verifying' && <Alert type="info" showIcon message="对象已上传，Verification Worker 正在校验魔数、大小与 SHA-256。" />}
        {state === 'error' && <Alert type="error" showIcon message="上传失败，可重新选择并重试。" />}
        <Button type="primary" block icon={<CloudUploadOutlined />} loading={state === 'uploading' || state === 'verifying'} disabled={!file} onClick={startUpload}>开始上传并分析</Button>
        <UploadHint>最大 256 MiB；full-memory 在 Phase 1 直接拒绝。原始对象下载受部署级开关控制。</UploadHint>
      </Space>
    </Card>
  )
}

export function WorkspaceOverviewPage({ workspace, onOpenOccurrence, onOpenGroup, onOpenBuild }: { workspace: Workspace; onOpenOccurrence: (occurrenceId: string) => void; onOpenGroup: (groupId: string) => void; onOpenBuild: (buildId: string) => void }) {
  void onOpenOccurrence
  void onOpenGroup
  void onOpenBuild
  const recentWindow = useMemo(() => {
    const to = new Date()
    const from = new Date(to.getTime() - 7 * 24 * 60 * 60 * 1_000)
    return { from: from.toISOString(), to: to.toISOString() }
  }, [])
  const { data: overview, isLoading, isError, refetch } = useWorkspaceOverview(workspace.id, recentWindow)
  const { data: builds } = useBuilds(workspace.id)

  if (isLoading) return <LoadingState rows={6} title />
  if (isError || !overview) return <ErrorState description="概览加载失败" onRetry={() => void refetch()} />

  return (
    <div>
      <PageTitle kicker={`${workspace.display_name} / OVERVIEW`} title="Workspace 概览" description="最近 7 天 · 统计只读取每个 Occurrence 的 Current Analysis" extra={<Space><Tag color="green">匿名内网</Tag><Tag color="geekblue">{workspace.default_architecture}</Tag></Space>} />
      <div className="metric-grid">
        <MetricCard label="Crash Occurrence" value={overview.crash_occurrences} hint="不同 DMP 内容计一次，reprocess 不增加" tone="blue" />
        <MetricCard label="Exact Groups" value={overview.exact_groups} hint="有精确证据才入组" tone="green" />
        <MetricCard label="Unclassified" value={overview.unclassified} hint="证据不足时保持正常路径" tone="orange" />
        <MetricCard label="平均分析耗时" value={formatDuration(overview.average_analysis_duration_ms)} hint={`失败率 ${(overview.failure_rate * 100).toFixed(1)}%`} tone="neutral" />
      </div>
      <Row gutter={[24, 24]}>
        <Col xs={24} lg={14} xl={16}>
          <Card title="按 Version 聚合" extra={<Text type="secondary">Version 不是 Build 唯一键</Text>} className="section-card">
            <DataTable rowKey={(row) => row.version ?? 'unknown'} dataSource={overview.versions} minWidth={520} columns={[{ title: 'Version', dataIndex: 'version', render: (value: string | null) => value ?? <Tag>未知版本</Tag> }, { title: 'Crash Occurrence', dataIndex: 'count', width: 170, align: 'right', className: 'cc-num', render: (value: number) => <Text strong>{value}</Text> }, { title: '占比', key: 'ratio', width: 160, align: 'right', render: (_, row) => <Progress percent={Math.round((row.count / Math.max(overview.crash_occurrences, 1)) * 100)} showInfo={false} size="small" /> }]} />
          </Card>
          <Card title="Top Exact Groups" className="section-card" extra={<Link to={routePaths.groups(workspace.id)}>查看全部 <ArrowRightOutlined /></Link>}>
            <List dataSource={overview.top_groups} locale={{ emptyText: '还没有 Exact Group' }} renderItem={(group) => <List.Item actions={[<Link to={routePaths.group(workspace.id, group.id)}>查看</Link>]}>
              <List.Item.Meta avatar={<div className="group-index">{group.occurrence_count}</div>} title={<span>{group.title}</span>} description={<Space size={8}><StatusTag status={group.status} /><HashValue value={group.fingerprint} length={18} /></Space>} />
            </List.Item>} />
          </Card>
        </Col>
        <Col xs={24} lg={10} xl={8}>
          <Card title="快捷操作" className="section-card"><Space direction="vertical" style={{ width: '100%' }}><Link to={routePaths.upload(workspace.id)}><Button type="primary" block icon={<CloudUploadOutlined />}>上传 Dump</Button></Link><Link to={routePaths.occurrences(workspace.id)}><Button block>打开 Crash Inbox</Button></Link></Space></Card>
          <Card title="质量与运行健康" className="section-card">
            <Space direction="vertical" style={{ width: '100%' }} size={16}>
              <QualityScore score={overview.symbol_completeness} />
              <div className="health-row"><span>解析失败率</span><Text strong>{(overview.failure_rate * 100).toFixed(1)}%</Text></div>
              <Divider style={{ margin: '0' }} />
              <div className="separate-metrics"><Statistic title="Hang captures" value={overview.hang_captures} /><Statistic title="Unknown" value={overview.unknown_captures} /><Statistic title="Rejected uploads" value={overview.rejected_uploads} /></div>
              <Alert type="info" showIcon message="Hang / Unknown / Rejected 独立展示，不混入 Crash Occurrence。" />
            </Space>
          </Card>
          <Card title="最近 Build" className="section-card">
            <List size="small" dataSource={builds ?? []} renderItem={(build: Build) => <List.Item actions={[<Link to={routePaths.build(workspace.id, build.id)}>打开</Link>]}><List.Item.Meta title={build.version} description={<span>{build.build_number ?? '—'} · {build.modules.length} modules</span>} /></List.Item>} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
