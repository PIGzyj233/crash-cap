import { Alert, Button, Card, Empty, Progress, Skeleton, Space, Tag, Tooltip, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'
import type { AnalysisStatus, FrameTrust, GroupStatus, QualityWarning, ResolutionMethod, VerificationStatus } from '../types'
import { statusLabel } from '../api/polling'
import { palette, qualityColor } from '../theme/tokens'

const { Text, Title } = Typography

/**
 * Letter grade is a display-only derivation (docs/design.md §3.6): it is never
 * a Canonical contract field. Thresholds A>=0.90 / B>=0.75 / C>=0.50 / D<0.50.
 */
export function qualityGrade(score: number): 'A' | 'B' | 'C' | 'D' {
  if (score >= 0.9) return 'A'
  if (score >= 0.75) return 'B'
  if (score >= 0.5) return 'C'
  return 'D'
}

export function MetricCard({ label, value, hint, tone = 'neutral' }: { label: string; value: ReactNode; hint?: string; tone?: 'neutral' | 'blue' | 'green' | 'orange' | 'red' }) {
  return (
    <Card className={`metric-card metric-${tone}`} variant="borderless">
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
        <Title level={1} className="page-title" tabIndex={-1}>{title}</Title>
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

export function QualityScore({ score, compact = false, strokeColor }: { score: number; compact?: boolean; strokeColor?: string }) {
  const percent = Math.round(score * 100)
  const color = percent >= 90 ? qualityColor.a : percent >= 75 ? qualityColor.b : percent >= 50 ? qualityColor.c : qualityColor.d
  return (
    <div className={compact ? 'quality-score quality-compact' : 'quality-score'}>
      <div className="quality-score-header"><Text strong>Quality</Text><Text strong style={{ color }}>{qualityGrade(score)} · {percent}%</Text></div>
      <Progress percent={percent} showInfo={false} strokeColor={strokeColor ?? color} trailColor={palette.n100} size="small" />
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
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      {warnings.map((warning) => {
        const type = ['pdb_mismatch', 'pe_mismatch', 'corrupted', 'system_symbol_failed', 'symbolicator_failed'].includes(warning.code) ? 'error' : ['system_symbol_pending', 'missing_pdb', 'missing_pe', 'scan_frames'].includes(warning.code) ? 'warning' : 'info'
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

/**
 * Loading placeholder for content whose shape is known ahead of time.
 *
 * Deliberately a Skeleton and not a Spin: work of *unknown duration* (an
 * in-flight analysis run) keeps using Spin, because a pulsing skeleton implies
 * content is about to arrive.
 */
export function LoadingState({ rows = 3, title = false }: { rows?: number; title?: boolean }) {
  return <div className="skeleton-state"><Skeleton active title={title} paragraph={{ rows }} /></div>
}

export function EmptyState({ description, action }: { description: ReactNode; action?: ReactNode }) {
  return <div className="center-state"><Empty description={description}>{action}</Empty></div>
}

/** Retry is the dominant empty-state variant; this keeps `重试` in one place. */
export function ErrorState({ description, onRetry }: { description: ReactNode; onRetry?: () => void }) {
  return <EmptyState description={description} action={onRetry && <Button icon={<ReloadOutlined />} onClick={onRetry}>重试</Button>} />
}

/**
 * Mangled C++ symbols carry their signal at both ends — `Renderer::` at the
 * front, the overload tail at the back — and template noise in the middle, so
 * this truncates the middle rather than the tail. The full value is always
 * available in the expanded row detail, which never truncates.
 */
export function SymbolText({ value, head = 30, tail = 18 }: { value: string | null | undefined; head?: number; tail?: number }) {
  if (!value) return <Text type="secondary">—</Text>
  if (value.length <= head + tail + 1) return <span className="cc-symbol">{value}</span>
  return (
    <Tooltip title={value}>
      <span className="cc-symbol">{value.slice(0, head)}…{value.slice(-tail)}</span>
    </Tooltip>
  )
}

/** Paths truncate at the head: `…/render/frame.cpp:120` is the identifying part. */
export function PathText({ file, line }: { file: string | null | undefined; line?: number | null }) {
  if (!file) return <Text type="secondary">—</Text>
  const label = `${file}:${line ?? '—'}`
  return <Tooltip title={label}><span className="cc-path">{label}</span></Tooltip>
}
