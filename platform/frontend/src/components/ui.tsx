import { Alert, Card, Progress, Space, Tag, Typography } from 'antd'
import type { ReactNode } from 'react'
import type { AnalysisStatus, FrameTrust, GroupStatus, QualityWarning, ResolutionMethod, VerificationStatus } from '../types'
import { statusLabel } from '../api/polling'

const { Text, Title } = Typography

export function MetricCard({ label, value, hint, tone = 'neutral' }: { label: string; value: ReactNode; hint?: string; tone?: 'neutral' | 'blue' | 'green' | 'orange' | 'red' }) {
  return (
    <Card className={`metric-card metric-${tone}`} bordered={false}>
      <Text className="metric-label">{label}</Text>
      <Title level={2} className="metric-value">{value}</Title>
      {hint && <Text type="secondary" className="metric-hint">{hint}</Text>}
    </Card>
  )
}

export function PageTitle({ kicker, title, description, extra }: { kicker?: string; title: string; description?: string; extra?: ReactNode }) {
  return (
    <div className="page-title-row">
      <div>
        {kicker && <div className="page-kicker">{kicker}</div>}
        <Title level={1} className="page-title">{title}</Title>
        {description && <Text type="secondary" className="page-description">{description}</Text>}
      </div>
      {extra && <div className="page-title-extra">{extra}</div>}
    </div>
  )
}

export function StatusTag({ status }: { status: AnalysisStatus | VerificationStatus | GroupStatus | ResolutionMethod | string }) {
  const text = statusLabel(status as AnalysisStatus)
  const color = status === 'COMPLETE' || status === 'PARTIAL' || status === 'verified' || status === 'matched' || status === 'auto_unique' || status === 'manual' || status === 'open' ? 'green' :
    status === 'FAILED' || status === 'REJECTED' || status === 'TIMEOUT' || status === 'OOM' || status === 'pdb_mismatch' || status === 'pe_mismatch' || status === 'mismatch' ? 'red' :
      status === 'ANALYZING' || status === 'QUEUED' || status === 'pending' || status === 'missing' || status === 'missing_pdb' || status === 'missing_pe' || status === 'ambiguous' || status === 'investigating' ? 'orange' : 'blue'
  return <Tag color={color}>{text}</Tag>
}

export function QualityScore({ score, compact = false }: { score: number; compact?: boolean }) {
  const percent = Math.round(score * 100)
  const color = percent >= 90 ? '#39c79a' : percent >= 75 ? '#4e8cff' : percent >= 50 ? '#f6ad55' : '#ff6b7a'
  return (
    <div className={compact ? 'quality-score quality-compact' : 'quality-score'}>
      <div className="quality-score-header"><Text strong>Quality</Text><Text strong style={{ color }}>{percent}%</Text></div>
      <Progress percent={percent} showInfo={false} strokeColor={color} trailColor="#edf1fa" size="small" />
    </div>
  )
}

export function TrustTag({ trust }: { trust: FrameTrust }) {
  const labels: Record<FrameTrust, string> = { context: 'context', cfi: 'cfi', frame_pointer: 'frame ptr', scan: 'scan · 低可信', unknown: 'unknown' }
  const color = trust === 'context' || trust === 'cfi' ? 'green' : trust === 'frame_pointer' ? 'blue' : trust === 'scan' ? 'orange' : 'default'
  return <Tag color={color}>{labels[trust]}</Tag>
}

export function WarningList({ warnings }: { warnings: QualityWarning[] }) {
  if (!warnings.length) return <Alert type="success" showIcon message="没有质量警告" />
  return (
    <Space direction="vertical" size={8} className="warning-list">
      {warnings.map((warning) => {
        const type = ['pdb_mismatch', 'pe_mismatch', 'corrupted', 'system_symbol_failed'].includes(warning.code) ? 'error' : ['system_symbol_pending', 'missing_pdb', 'missing_pe', 'scan_frames'].includes(warning.code) ? 'warning' : 'info'
        return <Alert key={`${warning.code}-${warning.message}`} type={type} showIcon message={<span><Text code>{warning.code}</Text> {warning.message}</span>} />
      })}
    </Space>
  )
}

export function HashValue({ value, length = 16 }: { value: string | null | undefined; length?: number }) {
  if (!value) return <Text type="secondary">—</Text>
  return <Text copyable={{ text: value }} code title={value}>{value.length > length ? `${value.slice(0, length)}…` : value}</Text>
}

export function UploadHint({ children }: { children: ReactNode }) {
  return <div className="upload-hint">{children}</div>
}
