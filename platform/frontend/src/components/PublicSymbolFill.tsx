import { useMutation,useQuery } from '@tanstack/react-query'
import { Alert,Button,Collapse,Space,Tag,Typography } from 'antd'
import { useRef } from 'react'
import { useApi } from '../api/context'
import { createUuid } from '../uuid'

const labels: Record<string, string> = {
  pending: '等待下载', fetching: '正在下载与校验', downloaded: '已补齐并校验',
  not_found: 'Windows 符号服务器未找到', failed: '下载或校验失败', identity_mismatch: 'PDB 身份不匹配', skipped: '跳过',
}
const reasons: Record<string, string> = {
  private_selection: '此模块已选择私有符号，或其配对存在冲突/不可用', already_available: '已有可用 PDB',
  debug_identity_unavailable: '缺少有效的 PDB 文件名或 GUID/Age', target_limit: '超出本次模块数量上限',
  public_symbol_job_budget_exhausted: '本次任务时间预算已用尽', public_symbol_timeout: '请求或校验超时',
}

export function PublicSymbolFill({ workspaceId, occurrenceId }: { workspaceId: string; occurrenceId: string }) {
  const api = useApi()
  const pending = useRef<string | null>(null)
  const job = useQuery({ queryKey: ['public-symbol-job', workspaceId, occurrenceId],
    queryFn: () => api.getPublicSymbolJob(workspaceId, occurrenceId), retry: false,
    refetchInterval: current => ['queued', 'running'].includes(current.state.data?.status ?? '') ? 2000 : false })
  const start = useMutation({ mutationFn: async () => {
    const key = pending.current ?? createUuid()
    pending.current = key
    const result = await api.createPublicSymbolJob(workspaceId, occurrenceId, { idempotency_key: key })
    pending.current = null
    await job.refetch()
    return result
  } })
  const active = ['queued', 'running'].includes(job.data?.status ?? '')
  const items = job.data?.items ?? []
  const count = (status: string) => items.filter(item => item.status === status).length
  return <Space direction="vertical" size="small" style={{ width: '100%', marginBlock: 12 }}>
    <Space wrap><Button loading={active || start.isPending} disabled={job.isPending || job.isError} onClick={() => start.mutate()}>补齐 Windows 公共符号</Button>
      <Typography.Text type="secondary">按缺失模块的精确 PDB 身份补充缓存；完成后可按需重新分析。</Typography.Text></Space>
    {(start.isError || job.isError) && <Alert type="warning" message={start.error?.message ?? '公共符号任务状态读取失败'} action={<Button onClick={() => void job.refetch()}>刷新</Button>} />}
    {job.data && <div role="status" aria-live="polite"><Typography.Text>{active ? (job.data.status === 'queued' ? '公共符号任务已排队' : '正在补齐公共符号') : job.data.status === 'failed' ? '公共符号任务失败' : '公共符号任务已结束'} · 已补齐 {count('downloaded')} · 未找到 {count('not_found')} · 失败 {count('failed') + count('identity_mismatch')} · 跳过 {count('skipped')}</Typography.Text></div>}
    {job.data && <Collapse size="small" items={[{ key: 'public', label: '查看公共符号处理结果', children: <Space direction="vertical" style={{ width: '100%' }}>
      {job.data.error_code && <Alert type="error" message={job.data.error_code === 'PUBLIC_SYMBOL_EVIDENCE_INVALID' ? '模块检查结果校验失败，无法安全定位公共符号。' : '公共符号任务执行失败。'} />}
      {items.map((item, index) => <div key={index}><Tag>{labels[String(item.status)] ?? '未知'}</Tag><Typography.Text>{String(item.debug_file ?? item.code_file ?? '未知模块')}</Typography.Text><Typography.Text type="secondary"> {reasons[String(item.reason)] ?? ''}</Typography.Text>{typeof item.debug_id === 'string' && <Typography.Text code>{item.debug_id}</Typography.Text>}</div>)}
    </Space> }]} />}
  </Space>
}
