import { Select } from 'antd'
import { useEffect, useState } from 'react'
import { authRequest, type UserIdentity } from '../api/authTransport'
export function UserSelect({ value, onChange, humansOnly = false }: { value?: string | null; onChange: (id: string | undefined) => void; humansOnly?: boolean }) {
  const [users, setUsers] = useState<UserIdentity[]>([])
  const [query, setQuery] = useState('')
  useEffect(() => {
    let active = true
    const timer = setTimeout(() => { void authRequest<UserIdentity[]>(`/users?q=${encodeURIComponent(query)}&limit=100`).then(rows => { if (active) setUsers(rows) }).catch(() => {}) }, 200)
    return () => { active = false; clearTimeout(timer) }
  }, [query])
  return <Select aria-label={humansOnly ? '负责人' : '上传人'} placeholder={humansOnly ? '选择负责人' : '所有上传人'} showSearch allowClear filterOption={false} onSearch={setQuery} style={{ minWidth: 180 }} value={value ?? undefined} onChange={onChange} options={users.filter(user => !humansOnly || user.kind === 'human' && user.enabled).map(user => ({ value: user.id, label: `${user.display_name} (${user.username})` }))} />
}
