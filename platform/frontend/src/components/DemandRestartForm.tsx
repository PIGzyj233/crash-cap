import { Alert,Button,Input,Space,Typography } from 'antd'
import { useRef,useState } from 'react'
import { CrashCapApiError } from '../api/client'
import { useApi } from '../api/context'
import { useCapabilities } from '../api/hooks'
import type { components } from '../generated/openapi'

type Restart = components['schemas']['DemandRestartRequest']
type Demand = components['schemas']['DemandStatusResponse']
type Props = { workspaceId: string; occurrenceId: string; demand: Demand | null; onSaved: () => void }

function readPending(key: string): Restart | null {
  const raw = sessionStorage.getItem(key)
  if (!raw) return null
  const value = JSON.parse(raw)
  const request = value.request as Restart
  if (value.version !== 1 || !request || typeof request.idempotency_key !== 'string'
    || !request.idempotency_key.trim() || request.idempotency_key.length > 200
    || typeof request.rationale !== 'string' || !request.rationale.trim() || request.rationale.length > 2000
    || ![request.expected_generation, request.expected_sequence].every((v) => Number.isSafeInteger(v) && v >= 0)) {
    throw new Error('无法恢复此前的重开请求，请先核对分析更新状态。')
  }
  return request
}

export function DemandRestartForm({ workspaceId, occurrenceId, demand, onSaved }: Props) {
  const api = useApi()
  const capabilities = useCapabilities()
  const enabled = capabilities.data?.enabled_writes.includes('analysis_demand_restarts') === true
  const key = `crashcap.demand-restart.v1:${import.meta.env.VITE_ANALYSIS_API_BASE_URL ?? import.meta.env.VITE_API_BASE_URL ?? '/api/v1'}:${workspaceId}:${occurrenceId}`
  const [initial] = useState(() => { try { return { request: readPending(key), error: null } } catch { return { request: null, error: '无法恢复此前的重开请求，请先核对分析更新状态。' } } })
  const pending = useRef<Restart | null>(initial.request)
  const sending = useRef(false)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [rejected, setRejected] = useState(false)
  const [rationale, setRationale] = useState(initial.request?.rationale ?? '')
  const [error, setError] = useState<string | null>(initial.error)
  const [warning, setWarning] = useState<string | null>(initial.request ? '已恢复结果尚未确认的重开请求。' : null)
  if (demand?.state !== 'retry_exhausted' && !pending.current && !error && !saved) return null
  const submit = async () => {
    if (sending.current || saved || rejected || initial.error || (!pending.current && (!enabled || demand?.state !== 'retry_exhausted' || !rationale.trim()))) return
    const body = pending.current ?? { idempotency_key: crypto.randomUUID(), expected_generation: demand!.generation, expected_sequence: demand!.change_sequence, rationale: rationale.trim() }
    // Persist before sending so a reload resends the same request.
    try { sessionStorage.setItem(key, JSON.stringify({ version: 1, request: body })) }
    catch { setError('无法暂存重开请求，尚未提交。请恢复浏览器存储后重试。'); return }
    pending.current = body
    sending.current = true; setBusy(true); setError(null)
    try {
      await api.restartAnalysisDemand(workspaceId, occurrenceId, body)
      setSaved(true)
      try { sessionStorage.removeItem(key); setWarning(null) }
      catch { setWarning('请求已受理，但暂存记录未清除；刷新后可再次确认同一请求。') }
      onSaved()
    } catch (failure) {
      setRejected(failure instanceof CrashCapApiError && failure.status === 409
        && ['STALE_DEMAND', 'DEMAND_NOT_EXHAUSTED', 'AUTOMATIC_ANALYSIS_DISABLED', 'AUTOMATIC_ANALYSIS_PAUSED'].includes(failure.code ?? ''))
      setError(failure instanceof Error ? failure.message : '重开请求未确认，请重试同一请求。')
    }
    finally { sending.current = false; setBusy(false) }
  }
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Typography.Text>{demand?.state === 'retry_exhausted' ? '自动重试已停止。确认故障已处理后，可请求重新分析。' : '正在确认此前的重新分析请求。'}当前报告会保留至新结果通过比较。</Typography.Text>
    {!enabled && !pending.current && <Alert type="info" message="此部署暂未启用人工重开分析" />}
    <Input.TextArea aria-label="重新分析说明" placeholder="说明已处理的问题和重新分析的原因" maxLength={2000} value={rationale} disabled={busy || saved || !!pending.current || !enabled} onChange={(event) => setRationale(event.target.value)} />
    {warning && <Alert type="warning" message={warning} />}
    {error && <Alert type="error" message={error} description={rejected ? '服务端已明确拒绝此请求。可清除该请求并刷新状态后重新操作。' : pending.current ? '重试会发送此前的同一请求，不会另开一个周期。' : undefined} />}
    {rejected && <Button onClick={() => {
      try { sessionStorage.removeItem(key) }
      catch { setError('无法清除已拒绝的请求，请恢复浏览器存储后重试。'); return }
      pending.current = null; setRejected(false); setWarning(null); setError(null); onSaved()
    }}>清除已拒绝请求并刷新状态</Button>}
    {saved && <Alert type="success" message="重新分析请求已受理，尚未完成分析。" />}
    <Button type="primary" loading={busy} disabled={saved || rejected || !!initial.error || (!pending.current && (!enabled || demand?.state !== 'retry_exhausted' || !rationale.trim()))} onClick={() => void submit()}>{saved ? '请求已受理' : pending.current ? '确认此前重开请求' : '请求重新分析'}</Button>
  </Space>
}
