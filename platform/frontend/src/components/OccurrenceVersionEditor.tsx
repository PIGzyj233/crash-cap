import { useMutation,useQueryClient } from '@tanstack/react-query'
import { Alert,Button,Input,Modal,Space,Typography } from 'antd'
import { useState } from 'react'
import { useApi } from '../api/context'
import type { OccurrenceDetail } from '../types'

export function OccurrenceVersionEditor({ occurrence }: { occurrence: OccurrenceDetail }) {
  const api = useApi(); const queries = useQueryClient()
  const [open, setOpen] = useState(false); const [version, setVersion] = useState('')
  const edit = useMutation({ mutationFn: () => api.editOccurrenceVersion(occurrence.id, version.trim() || null), onSuccess: async () => { setOpen(false); await queries.invalidateQueries() } })
  return <Space style={{ marginBlock: 16 }}><Typography.Text>当前版本：{occurrence.version ?? '未声明版本'}</Typography.Text><Button size="small" onClick={() => { setVersion(occurrence.version ?? ''); setOpen(true) }}>编辑版本</Button><Modal title="编辑 DMP 版本" open={open} onCancel={() => setOpen(false)} onOk={() => edit.mutate()} confirmLoading={edit.isPending}><Input aria-label="DMP 版本" maxLength={200} value={version} onChange={event => setVersion(event.target.value)} placeholder="留空为未声明版本" /><Typography.Paragraph type="secondary">保存后立即更新列表和统计，保留修改记录。此次编辑不会重新分析或改写历史报告。</Typography.Paragraph>{edit.isError && <Alert type="error" message={edit.error.message} />}</Modal></Space>
}
