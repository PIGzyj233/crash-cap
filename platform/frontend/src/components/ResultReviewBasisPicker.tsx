import { Alert,Button,Checkbox,Space,Typography } from 'antd'
import { useState } from 'react'
import { useApi } from '../api/context'
import type { components } from '../generated/openapi'
import type { CanonicalReport } from '../types'

type Basis = components['schemas']['ResultReviewRequest']['basis_reviews'][number]
type Option = { pairId: string; label: string; state: 'active' | 'withdrawn' }

export function reviewPairChanges(before: CanonicalReport, after: CanonicalReport): Option[] {
  const selected = (report: CanonicalReport) => new Map(report.schema_version === '2.0'
    ? report.modules.flatMap((module) => module.selection.selected_pair_id ? [[module.selection.selected_pair_id, module.code_file] as const] : []) : [])
  const old = selected(before), next = selected(after)
  return [
    ...[...old].filter(([id]) => !next.has(id)).map(([pairId, name]) => ({ pairId, label: `${name} · 审核前使用`, state: 'withdrawn' as const })),
    ...[...next].filter(([id]) => !old.has(id)).map(([pairId, name]) => ({ pairId, label: `${name} · 候选使用`, state: 'active' as const })),
  ]
}

function PairBasis({ option, value, onChange, disabled }: { option: Option; value: Basis[]; onChange: (value: Basis[]) => void; disabled: boolean }) {
  const api = useApi()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState<{ review: components['schemas']['CatalogReviewResponse']; evidence: components['schemas']['CatalogReviewEvidence'] } | null>(null)
  const load = async () => {
    setBusy(true); setError(null); setLoaded(null)
    try {
      const [origins, page] = await Promise.all([api.getCatalogOrigins(option.pairId), api.getCatalogReviews(option.pairId)])
      const review = page.items.find((item) => item.qualification_version === origins.qualification_version && item.state === origins.state)
      if (!review || review.state !== option.state) throw new Error('当前没有支持此报告变化的有效提供方复核。')
      const evidence = await api.getCatalogReviewEvidence(option.pairId, review.id)
      setLoaded({ review, evidence })
    } catch (failure) { setError(failure instanceof Error ? failure.message : '读取依据失败') }
    finally { setBusy(false) }
  }
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Typography.Text>{option.label}</Typography.Text>
    <Button disabled={disabled} loading={busy} onClick={() => void load()}>查看当前提供方依据</Button>
    {error && <Alert type="warning" message={error} />}
    {loaded && !error && <>
      <Typography.Text>{loaded.review.state === 'withdrawn' ? '逻辑停用' : '恢复资格'}：{loaded.review.reason}</Typography.Text>
      <Typography.Text>复核人声明：{loaded.evidence.reviewer}</Typography.Text>
      <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{loaded.evidence.evidence}</Typography.Paragraph>
      <Checkbox disabled={disabled || (value.length >= 200 && !value.some((item) => item.review_id === loaded.review.id))} checked={value.some((item) => item.review_id === loaded.review.id)} onChange={(event) => onChange(event.target.checked ? [...value.filter((item) => item.review_id !== loaded.review.id), { review_id: loaded.review.id, evidence_sha256: loaded.review.evidence_sha256 }] : value.filter((item) => item.review_id !== loaded.review.id))}>引用这条已查看的依据</Checkbox>
    </>}
  </Space>
}

export function ResultReviewBasisPicker({ options, value, onChange, disabled }: { options: Option[]; value: Basis[]; onChange: (value: Basis[]) => void; disabled: boolean }) {
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Typography.Text type="secondary">从双方报告变化的配对中查看并引用依据；提交时服务端会重新检查资格。</Typography.Text>
    {!options.length && <Typography.Text>双方报告没有可引用复核的配对变化。</Typography.Text>}
    {options.map((option) => <PairBasis key={option.pairId} option={option} value={value} onChange={onChange} disabled={disabled} />)}
  </Space>
}
