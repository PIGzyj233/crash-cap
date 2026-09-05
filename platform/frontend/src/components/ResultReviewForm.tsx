import { Alert,Button,Checkbox,Input,Modal,Select,Space,Typography } from 'antd'
import { useRef,useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../api/context'
import { useCapabilities } from '../api/hooks'
import type { components } from '../generated/openapi'
import { ResultReviewBasisPicker,reviewPairChanges } from './ResultReviewBasisPicker'

type Review = components['schemas']['ResultReviewRequest']
type Props = { workspaceId: string; occurrenceId: string; currentRunId: string; candidateRunId: string; onSaved: () => void }

function storageKey({ workspaceId, occurrenceId, candidateRunId }: Pick<Props, 'workspaceId' | 'occurrenceId' | 'candidateRunId'>) {
  return `crashcap.result-review.v1:${import.meta.env.VITE_ANALYSIS_API_BASE_URL ?? import.meta.env.VITE_API_BASE_URL ?? '/api/v1'}:${workspaceId}:${occurrenceId}:${candidateRunId}`
}

function restore(key: string, candidate: string): Review | null {
  const raw = sessionStorage.getItem(key)
  if (!raw) return null
  const value = JSON.parse(raw) as Review
  if (value.schema_version !== 'result-review-request-v1' || value.candidate_run_id !== candidate
    || !value.current_run_id || !value.idempotency_key || !value.reviewed_by?.trim() || !value.rationale?.trim()
    || !['engine_upgrade', 'role_change', 'evidence_correction'].includes(value.cause)
    || ![value.current_canonical_sha256, value.candidate_canonical_sha256].every((sha) => /^[a-f0-9]{64}$/.test(sha))
    || !Array.isArray(value.basis_reviews) || value.basis_reviews.some((basis) => !basis.review_id || !/^[a-f0-9]{64}$/.test(basis.evidence_sha256))) throw new Error('暂存审核内容不完整，请先核对审核历史')
  return value
}

function FormBody({ workspaceId, occurrenceId, currentRunId, candidateRunId, onSaved }: Props) {
  const api = useApi()
  const capabilities = useCapabilities()
  const enabled = capabilities.data?.enabled_writes.includes('result_reviews') === true
  const key = storageKey({ workspaceId, occurrenceId, candidateRunId })
  const [initial] = useState(() => { try { return { request: restore(key, candidateRunId), warning: null } } catch { return { request: null, warning: '无法恢复暂存审核，请先核对审核历史。' } } })
  const pending = useRef<Review | null>(initial.request)
  const [warning, setWarning] = useState<string | null>(initial.warning)
  const [cause, setCause] = useState<Review['cause']>(initial.request?.cause ?? 'engine_upgrade')
  const [reviewer, setReviewer] = useState(initial.request?.reviewed_by ?? '')
  const [rationale, setRationale] = useState(initial.request?.rationale ?? '')
  const [basis, setBasis] = useState<Review['basis_reviews']>(initial.request?.basis_reviews ?? [])
  const [binding, setBinding] = useState<{ current: string; currentSha: string; candidateSha: string } | null>(null)
  const [pairChanges, setPairChanges] = useState<ReturnType<typeof reviewPairChanges>>([])
  const [confirmed, setConfirmed] = useState(!!initial.request)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(initial.request ? '已恢复结果尚未确认的审核请求。' : null)
  const [saved, setSaved] = useState(false)
  const locked = busy || pending.current !== null || saved
  const oldId = pending.current?.current_run_id ?? binding?.current ?? currentRunId
  const path = `/w/${encodeURIComponent(workspaceId)}/occurrences/${encodeURIComponent(occurrenceId)}`
  const load = async () => {
    setBusy(true); setError(null); setConfirmed(false)
    try {
      const [old, next] = await Promise.all([api.getReviewReport(occurrenceId, currentRunId), api.getReviewReport(occurrenceId, candidateRunId)])
      setPairChanges(reviewPairChanges(old.report, next.report)); setBasis([])
      setBinding({ current: currentRunId, currentSha: old.sha256, candidateSha: next.sha256 })
    } catch (failure) { setError(failure instanceof Error ? failure.message : '读取报告失败') }
    finally { setBusy(false) }
  }
  const submit = async () => {
    if (busy || saved || !enabled || (!pending.current && (!binding || !confirmed))) return
    pending.current ??= { schema_version: 'result-review-request-v1', idempotency_key: crypto.randomUUID(), current_run_id: binding!.current, candidate_run_id: candidateRunId, current_canonical_sha256: binding!.currentSha, candidate_canonical_sha256: binding!.candidateSha, cause, reviewed_by: reviewer, rationale, basis_reviews: basis.map((item) => ({ ...item })) }
    try { sessionStorage.setItem(key, JSON.stringify(pending.current)) }
    catch { setWarning('无法暂存请求；确认结果前请保持页面。') }
    setBusy(true); setError(null)
    try {
      const result = await api.submitResultReview(workspaceId, occurrenceId, pending.current)
      try { sessionStorage.removeItem(key) } catch { setWarning('结果已保存，但暂存记录未清除；刷新后请核对历史。') }
      setSaved(true); setError(null)
      setWarning(result.decision === 'promote' || result.decision === 'correct' ? '审核已保存并采用候选报告。' : '审核已保存，当前报告未替换，请查看审核记录。')
      onSaved()
    } catch (failure) { setError(failure instanceof Error ? failure.message : '审核提交失败') }
    finally { setBusy(false) }
  }
  return <Space direction="vertical" style={{ width: '100%' }}>
    {!enabled && <Alert type="info" message="此部署尚未启用报告审核写入" />}
    <Space wrap><Link to={`${path}?run=${encodeURIComponent(oldId)}`} target="_blank" rel="noopener noreferrer">打开审核前报告</Link><Link to={`${path}?run=${encodeURIComponent(candidateRunId)}`} target="_blank" rel="noopener noreferrer">打开候选报告</Link></Space>
    <Typography.Text type="secondary">审核人是人工声明。审核将绑定这两份报告，提交时服务端会重新检查当前报告及证据。</Typography.Text>
    {!pending.current && <Button onClick={() => void load()} loading={busy} disabled={!enabled || saved || currentRunId >= candidateRunId}>读取并绑定两份报告</Button>}
    {binding && <Typography.Text>已绑定报告，可查看后填写审核结论。</Typography.Text>}
    <Select aria-label="报告审核原因" value={cause} onChange={setCause} disabled={locked || !enabled} options={[{ value: 'engine_upgrade', label: '分析引擎升级' }, { value: 'role_change', label: '模块归属变更' }, { value: 'evidence_correction', label: '证据纠正' }]} />
    <Input aria-label="报告审核人" placeholder="审核人声明" value={reviewer} maxLength={200} disabled={locked || !enabled} onChange={(event) => setReviewer(event.target.value)} />
    <Input.TextArea aria-label="报告审核说明" placeholder="核对过程和采用此解释的依据" value={rationale} maxLength={4000} disabled={locked || !enabled} onChange={(event) => setRationale(event.target.value)} />
    {binding && !pending.current && <ResultReviewBasisPicker key={`${binding.current}:${binding.currentSha}:${binding.candidateSha}`} options={pairChanges} value={basis} onChange={(value) => { setBasis(value); setConfirmed(false) }} disabled={locked || !enabled} />}
    {basis.map((item, index) => <Space key={item.review_id} wrap>
      <Typography.Text>已引用依据 {index + 1}：{item.review_id}</Typography.Text>
      <Button disabled={locked || !enabled} onClick={() => { setBasis(basis.filter((_, i) => i !== index)); setConfirmed(false) }}>移除此依据</Button>
    </Space>)}
    <Checkbox checked={confirmed} disabled={locked || !enabled || !binding} onChange={(event) => setConfirmed(event.target.checked)}>已查看双方报告并核对审核依据，确认提交</Checkbox>
    {warning && <Alert type={saved ? 'success' : 'warning'} message={warning} />}
    {error && <Alert type="error" message={error} description={pending.current ? '重试将发送原请求与原幂等键，不会重新绑定报告。' : undefined} />}
    {pending.current && error && <Button disabled={busy} onClick={() => { try { sessionStorage.removeItem(key) } catch { setWarning('无法清除暂存请求'); return } pending.current = null; setBinding(null); setConfirmed(false); setError(null) }}>核对历史后放弃此请求</Button>}
    <Button type="primary" loading={busy} disabled={!enabled || saved || !confirmed || !reviewer.trim() || !rationale.trim() || (cause === 'evidence_correction' && !basis.length) || basis.some((item) => !item.review_id.trim() || !/^[a-f0-9]{64}$/.test(item.evidence_sha256))} onClick={() => void submit()}>{saved ? '审核已保存' : pending.current ? '重试相同报告审核' : '提交报告审核'}</Button>
  </Space>
}

export function ResultReviewForm(props: Props) {
  const [open, setOpen] = useState(false)
  let hasPending = false
  try { hasPending = sessionStorage.getItem(storageKey(props)) !== null }
  catch { hasPending = true }
  const canStart = props.currentRunId < props.candidateRunId
  return <>
    {(canStart || hasPending) && <Button onClick={() => setOpen(true)}>{hasPending ? '确认此前审核结果' : '审核此候选报告'}</Button>}
    <Modal title="审核候选报告" open={open} onCancel={() => setOpen(false)} footer={null} width={760} style={{ maxWidth: 'calc(100vw - 32px)', top: 24 }} styles={{ body: { maxHeight: 'calc(100dvh - 144px)', overflowY: 'auto', overflowWrap: 'anywhere' } }} destroyOnHidden maskClosable={false}>
      {open && <FormBody {...props} />}
    </Modal>
  </>
}
