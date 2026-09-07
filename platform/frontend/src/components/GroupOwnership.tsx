import { Alert, Button, Card, Select, Space, Typography } from 'antd'
import { useState } from 'react'
import { authRequest } from '../api/authTransport'
import { UserSelect } from './UserSelect'
export function GroupOwnership({ group, onSaved }: { group: { id: string; owner?: string | null; owner_user_id?: string | null; status: string }; onSaved: () => void }) {
  const [owner, setOwner] = useState(group.owner_user_id ?? undefined)
  const [status, setStatus] = useState(group.status)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  return <Card title="问题认定与负责人"><Space wrap><UserSelect humansOnly value={owner} onChange={setOwner} /><Select aria-label="问题状态" value={status} onChange={setStatus} options={[{ value: 'open', label: '待认定' }, { value: 'investigating', label: '排查中' }, { value: 'fixed', label: '已修复' }, { value: 'ignored', label: '已忽略' }]} /><Button loading={busy} onClick={async () => {
    setBusy(true); setError('')
    try { await authRequest(`/groups/${group.id}`, { method: 'PATCH', body: JSON.stringify({ status, owner_user_id: owner ?? null }) }); onSaved() }
    catch (failure) { setError(String(failure)) } finally { setBusy(false) }
  }}>保存</Button></Space>{!group.owner_user_id && group.owner && <Typography.Paragraph type="secondary">历史负责人：{group.owner}</Typography.Paragraph>}{error && <Alert type="error" message={error} />}</Card>
}
