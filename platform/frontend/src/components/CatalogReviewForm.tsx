import { useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, Select, Space } from 'antd'
import { useApi } from '../api/context'
import { useCapabilities } from '../api/hooks'
import type { components } from '../generated/openapi'

type Review = components['schemas']['CatalogReviewRequest']

function restoreRequest(key: string): { request: Review | null; warning: string | null } {
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return { request: null, warning: null }
    const value = JSON.parse(raw) as Partial<Review>
    if (!Number.isSafeInteger(value.expected_version) || Number(value.expected_version) < 1
      || !['active', 'withdrawn'].includes(value.state ?? '')
      || !(['reviewer', 'reason', 'evidence', 'idempotency_key'] as const).every((field) => typeof value[field] === 'string' && value[field]!.trim())) throw new Error('Invalid saved request')
    return { request: value as Review, warning: null }
  } catch {
    return { request: null, warning: '无法恢复本标签页的待确认请求。提交前请先核对复核历史。' }
  }
}

export function CatalogReviewForm({ pairId, version, onSaved }: { pairId: string; version: number; onSaved: () => void }) {
  const api = useApi()
  const capabilities = useCapabilities()
  const enabled = capabilities.data?.enabled_writes.includes('catalog_reviews') === true
  const storageKey = `crashcap.review.pending.v1:${import.meta.env.VITE_API_BASE_URL ?? '/api/v1'}:${pairId}`
  const [restored] = useState(() => restoreRequest(storageKey))
  const [storageWarning, setStorageWarning] = useState(restored.warning)
  const [state, setState] = useState<Review['state']>(restored.request?.state ?? 'withdrawn')
  const [reviewer, setReviewer] = useState(restored.request?.reviewer ?? '')
  const [reason, setReason] = useState(restored.request?.reason ?? '')
  const [evidence, setEvidence] = useState(restored.request?.evidence ?? '')
  const [confirmed, setConfirmed] = useState(restored.request !== null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(restored.request ? '已恢复尚未确认结果的复核请求。' : null)
  const [saved, setSaved] = useState(false)
  const request = useRef<Review | null>(restored.request)
  const locked = busy || request.current !== null
  const submit = async () => {
    if (busy || saved || !enabled) return
    request.current ??= { expected_version: version, state, reviewer, reason, evidence, idempotency_key: crypto.randomUUID() }
    try { sessionStorage.setItem(storageKey, JSON.stringify(request.current)) }
    catch { setStorageWarning('无法在本标签页暂存请求；结果确认前请勿刷新页面。') }
    setBusy(true); setError(null)
    try {
      await api.submitCatalogReview(pairId, request.current)
      try { sessionStorage.removeItem(storageKey) }
      catch { setStorageWarning('复核已保存，但本标签页暂存记录未能清除；刷新后请核对历史。') }
      setSaved(true)
      onSaved()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '复核提交失败')
    } finally { setBusy(false) }
  }
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Alert type="warning" showIcon message="提供方复核影响全平台对此配对的后续使用" description="停用保留文件和历史报告；恢复不保证身份冲突已经消除。请填写实际核查依据。复核人仅为人工声明。" />
    {!enabled && <Alert type="info" message="此部署尚未启用配对复核写入" />}
    {storageWarning && <Alert type="warning" message={storageWarning} />}
    <Select aria-label="复核结论" value={state} onChange={setState} disabled={locked || !enabled} options={[{ value: 'withdrawn', label: '逻辑停用此配对' }, { value: 'active', label: '恢复此配对资格' }]} />
    <Input aria-label="复核人" placeholder="复核人或提供方" value={reviewer} onChange={(event) => setReviewer(event.target.value)} maxLength={256} disabled={locked || !enabled} />
    <Input.TextArea aria-label="复核原因" placeholder="停用或恢复的原因" value={reason} onChange={(event) => setReason(event.target.value)} maxLength={2000} disabled={locked || !enabled} />
    <Input.TextArea aria-label="复核依据" placeholder="文件核对过程、结果和可追溯的依据" value={evidence} onChange={(event) => setEvidence(event.target.value)} maxLength={32000} rows={4} disabled={locked || !enabled} />
    <Checkbox checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={locked || !enabled}>已核对依据，确认提交此全局配对的复核结论</Checkbox>
    {error && <Alert type="error" message={error} description="重试会发送原内容、原资格版本和原幂等键。请求暂存于当前标签页；如需重新填写，请先核对已保存的复核历史。" />}
    {error && !busy && <Button onClick={() => {
      try { sessionStorage.removeItem(storageKey) }
      catch { setStorageWarning('无法清除暂存请求，请保持页面并重试。'); return }
      request.current = null; setError(null); setConfirmed(false)
    }}>核对历史后放弃此请求</Button>}
    {saved && <Alert type="success" message="复核已保存；历史报告保持原样，后续分析按目录变化处理。" />}
    <Button loading={busy} disabled={!enabled || saved || !confirmed || !reviewer.trim() || !reason.trim() || !evidence.trim()} onClick={() => void submit()}>{error ? '重试相同复核' : '提交复核结论'}</Button>
  </Space>
}
