import { useState } from 'react'
import { Alert, App as AntApp, Button, Card, Space, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { ReloadOutlined, WarningOutlined } from '@ant-design/icons'
import { useApi } from '../api/context'
import { useSymbolHealth } from '../api/hooks'
import type { SymbolHealthRow, Workspace } from '../types'
import { DataTable } from '../components/DataTable'
import { ErrorState, HashValue, LoadingState, MetricCard, PageTitle, StatusTag } from '../components/ui'

const { Text } = Typography

/** How many affected occurrences get their own link before collapsing to a count. */
const OCCURRENCE_LINK_LIMIT = 3

function symbolHealthColumns({
  busyModule,
  onOpenOccurrence,
  onOpenBuild,
  onBatchReprocess,
}: {
  busyModule: string | null
  onOpenOccurrence: (occurrenceId: string) => void
  onOpenBuild: (buildId: string) => void
  onBatchReprocess: (row: SymbolHealthRow) => void
}): TableColumnsType<SymbolHealthRow> {
  return [
    {
      title: '模块',
      dataIndex: 'code_file',
      fixed: 'left',
      width: 240,
      render: (value: string, row: SymbolHealthRow) => (
        <span>
          <Text strong>{value}</Text>
          <br />
          <Text type="secondary">{row.debug_file ?? '无 debug file'}</Text>
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: SymbolHealthRow['status']) => <StatusTag status={value === 'matched' ? 'verified' : value} />,
    },
    { title: 'code_id', dataIndex: 'code_id', width: 180, render: (value: string | null) => <HashValue value={value} /> },
    { title: 'debug_id', dataIndex: 'debug_id', width: 180, render: (value: string | null) => <HashValue value={value} /> },
    {
      title: '受影响 Occurrence',
      dataIndex: 'affected_occurrence_count',
      width: 300,
      render: (value: number, row: SymbolHealthRow) => {
        if (!value) return <Text type="secondary">0</Text>
        if (!row.occurrence_ids.length) return <Space wrap size={[0, 4]}><Text>{value} 个：</Text><Text type="secondary">暂无可用链接</Text></Space>
        // A module can affect dozens of occurrences; linking every one turns the
        // cell into a wall of buttons.
        const shown = row.occurrence_ids.slice(0, OCCURRENCE_LINK_LIMIT)
        const hidden = row.occurrence_ids.length - shown.length
        return (
          <Space wrap size={[0, 4]}>
            <Text>{value} 个：</Text>
            {shown.map((occurrenceId) => (
              <Button key={occurrenceId} type="link" onClick={() => onOpenOccurrence(occurrenceId)}>{occurrenceId} <ReloadOutlined /></Button>
            ))}
            {hidden > 0 && <Text type="secondary">还有 {hidden} 个</Text>}
          </Space>
        )
      },
    },
    {
      title: '补符号操作',
      key: 'actions',
      width: 280,
      render: (_, row: SymbolHealthRow) => (
        <Space>
          <Button disabled={!row.build_id} onClick={() => row.build_id && onOpenBuild(row.build_id)}>定位 Build</Button>
          <Button type="primary" disabled={!row.module_id || row.affected_occurrence_count === 0} loading={busyModule === row.module_id} onClick={() => onBatchReprocess(row)}>批量 Reprocess ({row.affected_occurrence_count})</Button>
        </Space>
      ),
    },
    { title: '最近发现', dataIndex: 'last_seen', width: 180, render: (value: string) => new Date(value).toLocaleString('zh-CN') },
  ]
}

export function SymbolHealthPage({ workspace, onOpenOccurrence, onOpenBuild }: { workspace: Workspace; onOpenOccurrence: (occurrenceId: string) => void; onOpenBuild: (buildId: string) => void }) {
  const api = useApi()
  const { message } = AntApp.useApp()
  const [busyModule, setBusyModule] = useState<string | null>(null)
  const { data: rows, isLoading, isError, refetch } = useSymbolHealth(workspace.id)
  const matched = rows?.filter((row) => row.status === 'matched').length ?? 0
  const missing = rows?.filter((row) => row.status === 'missing').length ?? 0
  const mismatch = rows?.filter((row) => row.status === 'mismatch').length ?? 0
  const batchReprocess = async (row: SymbolHealthRow) => {
    if (!row.module_id) return
    try {
      setBusyModule(row.module_id)
      const result = await api.batchReprocessSymbols(workspace.id, { module_id: row.module_id })
      message.success(`影响 ${result.affected_occurrence_count} 个 Occurrence，已创建 ${result.created_run_count} 个新 Run`)
      await refetch()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '批量 reprocess 失败')
    } finally {
      setBusyModule(null)
    }
  }

  return <div>
    <PageTitle kicker={`${workspace.display_name} / SYMBOL HEALTH`} title="Symbol Health" description="按模块聚合 matched / missing / mismatch；点击受影响 Occurrence 可直接下钻。" />
    <div className="metric-grid metric-grid-3">
      <MetricCard label="Matched" value={matched} hint="当前 Workspace 私有源或 allowlist 源" tone="green" />
      <MetricCard label="Missing" value={missing} hint="可补传 PE/PDB 后 reprocess" tone="orange" />
      <MetricCard label="Mismatch" value={mismatch} hint="错误 PDB 不会静默符号化" tone="red" />
    </div>
    <Card className="section-card">
      {isError ? <ErrorState description="符号健康加载失败" onRetry={() => void refetch()} />
        : isLoading ? <LoadingState rows={5} />
          : (
            <DataTable<SymbolHealthRow>
              rowKey={(row) => `${row.build_id ?? 'none'}-${row.module_id ?? row.code_file}`}
              dataSource={rows ?? []}
              pagination={{ pageSize: 12, showSizeChanger: false }}
              minWidth={1470}
              columns={symbolHealthColumns({ busyModule, onOpenOccurrence, onOpenBuild, onBatchReprocess: (row) => void batchReprocess(row) })}
            />
          )}
    </Card>
    {mismatch > 0 && <Alert className="page-alert" type="error" showIcon icon={<WarningOutlined />} message="发现 PDB mismatch" description="错误 PDB 必须显式标记为 mismatch，平台不会用它生成看似合理的符号。补传正确 PE/PDB 后请在 Occurrence 报告中触发 reprocess。" />}
    <div className="report-footnote">
      <Tag color="blue">补符号链路可恢复</Tag>
      先定位 Build 上传正确 PE/PDB，再按模块批量 reprocess；界面会显示精确影响范围，新 Run 不覆盖历史 Run。
    </div>
  </div>
}
