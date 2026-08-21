import { Alert, Button, Card, Empty, Space, Spin, Table, Typography } from 'antd'
import { ReloadOutlined, WarningOutlined } from '@ant-design/icons'
import { useSymbolHealth } from '../api/hooks'
import type { SymbolHealthRow, Workspace } from '../types'
import { HashValue, MetricCard, PageTitle, StatusTag } from '../components/ui'

const { Text } = Typography

export function SymbolHealthPage({ workspace, onOpenOccurrence }: { workspace: Workspace; onOpenOccurrence: (occurrenceId: string) => void }) {
  const { data: rows, isLoading, isError, refetch } = useSymbolHealth(workspace.id)
  const matched = rows?.filter((row) => row.status === 'matched').length ?? 0
  const missing = rows?.filter((row) => row.status === 'missing').length ?? 0
  const mismatch = rows?.filter((row) => row.status === 'mismatch').length ?? 0

  return <div>
    <PageTitle kicker={`${workspace.display_name} / SYMBOL HEALTH`} title="Symbol Health" description="按模块聚合 matched / missing / mismatch；点击受影响 Occurrence 可直接下钻。" />
    <div className="metric-grid metric-grid-3"><MetricCard label="Matched" value={matched} hint="当前 Workspace 私有源或 allowlist 源" tone="green" /><MetricCard label="Missing" value={missing} hint="可补传 PE/PDB 后 reprocess" tone="orange" /><MetricCard label="Mismatch" value={mismatch} hint="错误 PDB 不会静默符号化" tone="red" /></div>
    <Card className="section-card">
      {isError ? <Empty description="符号健康加载失败"><Button onClick={() => refetch()}>重试</Button></Empty> : isLoading ? <div className="center-state"><Spin /></div> : <Table rowKey={(row) => `${row.code_file}-${row.debug_id ?? 'none'}-${row.status}`} dataSource={rows ?? []} pagination={{ pageSize: 12, showSizeChanger: false }} scroll={{ x: 900 }} columns={[{ title: '模块', dataIndex: 'code_file', fixed: 'left', render: (value: string, row: SymbolHealthRow) => <span><Text strong>{value}</Text><br /><Text type="secondary">{row.debug_file ?? '无 debug file'}</Text></span> }, { title: '状态', dataIndex: 'status', render: (value: SymbolHealthRow['status']) => <StatusTag status={value === 'matched' ? 'verified' : value} /> }, { title: 'code_id', dataIndex: 'code_id', render: (value: string | null) => <HashValue value={value} /> }, { title: 'debug_id', dataIndex: 'debug_id', render: (value: string | null) => <HashValue value={value} /> }, { title: '受影响 Occurrence', dataIndex: 'affected_occurrence_count', render: (value: number, row: SymbolHealthRow) => value ? <Space wrap size={[0, 4]}><Text>{value} 个：</Text>{row.occurrence_ids.length ? row.occurrence_ids.map((occurrenceId) => <Button key={occurrenceId} type="link" onClick={() => onOpenOccurrence(occurrenceId)}>{occurrenceId} <ReloadOutlined /></Button>) : <Text type="secondary">暂无可用链接</Text>}</Space> : <Text type="secondary">0</Text> }, { title: '最近发现', dataIndex: 'last_seen', render: (value: string) => new Date(value).toLocaleString('zh-CN') }]} />}
    </Card>
    {mismatch > 0 && <Alert className="page-alert" type="error" showIcon icon={<WarningOutlined />} message="发现 PDB mismatch" description="错误 PDB 必须显式标记为 mismatch，平台不会用它生成看似合理的符号。补传正确 PE/PDB 后请在 Occurrence 报告中触发 reprocess。" />}
    <Alert className="page-alert" type="info" showIcon message="Source bundle Phase 1 只保存 raw" description="源码上下文消费与 file/line 增强留在后续阶段；当前报告优先展示稳定 Canonical JSON 的函数与源码字段。" />
  </div>
}
