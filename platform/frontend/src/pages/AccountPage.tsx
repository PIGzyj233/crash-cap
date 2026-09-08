import { Alert, Avatar, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { authRequest, setIdentity, type LoginIdentity, type UserIdentity } from '../api/authTransport'
import { PasswordForm, useIdentity, useSessionReady } from '../components/Authentication'
import { LogoutButton } from '../components/LogoutButton'
import { PageTitle } from '../components/ui'

type Token = { id: string; name: string; expires_at: string; revoked_at: string | null; last_used_at: string | null }
export function TokensPanel({ service = false }: { service?: boolean }) {
  const ready = useSessionReady()
  const root = service ? '/admin/service-users/usr_ci/tokens' : '/me/tokens'
  const [rows, setRows] = useState<Token[]>([])
  const [secret, setSecret] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (!ready) setSecret('') }, [ready])
  const refresh = useCallback(async () => { try { setRows(await authRequest<Token[]>(root)) } catch (failure) { setError(String(failure)) } }, [root])
  useEffect(() => { if (ready) { setError(''); void refresh() } }, [refresh, ready])
  return <Card title={service ? 'CI 上传令牌' : '个人 CLI 上传令牌'}>
    <Typography.Paragraph>令牌仅可上传文件和查询上传结果。原文只显示一次；有效期默认 90 天。</Typography.Paragraph>
    {error && <Alert type="error" message={error} />}
    <Form layout="vertical" className="account-token-form" initialValues={{ expires_in_days: 90 }} onFinish={async values => {
      setBusy(true); setError('')
      try { const result = await authRequest<{ token: string }>(root, { method: 'POST', body: JSON.stringify(values) }); setSecret(result.token); await refresh() }
      catch (failure) { setError(String(failure)) } finally { setBusy(false) }
    }}>
      <Form.Item name="name" label="用途" rules={[{ required: true, whitespace: true }]}><Input placeholder="例如 nightly-build" maxLength={128} /></Form.Item>
      <Form.Item name="expires_in_days" label="有效天数"><InputNumber min={1} max={365} /></Form.Item>
      <Button htmlType="submit" type="primary" loading={busy}>创建令牌</Button>
    </Form>
    <Table<Token> className="account-table" rowKey="id" dataSource={rows} scroll={{ x: 640 }} columns={[
      { title: '名称', dataIndex: 'name' }, { title: '到期时间', dataIndex: 'expires_at', render: value => new Date(value).toLocaleString() },
      { title: '状态', render: (_, row) => row.revoked_at ? <Tag>已撤销</Tag> : new Date(row.expires_at) < new Date() ? <Tag>已过期</Tag> : <Tag color="green">有效</Tag> },
      { title: '操作', render: (_, row) => <Button disabled={!!row.revoked_at} onClick={async () => { try { await authRequest(`${root}/${row.id}:revoke`, { method: 'POST' }); await refresh() } catch (failure) { setError(String(failure)) } }}>撤销</Button> },
    ]} />
    <Modal title="保存令牌，此窗口关闭后无法再次查看" open={ready && !!secret} onCancel={() => setSecret('')} onOk={() => setSecret('')} destroyOnHidden>
      <Input.TextArea aria-label="新令牌" readOnly value={secret} autoSize />
      <Typography.Paragraph>将它保存到 CI 的 CRASHCAP_TOKEN 密钥变量，或保存到文件并使用 --token-file。不会自动写入浏览器存储。</Typography.Paragraph>
    </Modal>
  </Card>
}

export function AccountPage() {
  const user = useIdentity()
  const ready = useSessionReady()
  const [error, setError] = useState('')
  useEffect(() => { if (ready) setError('') }, [ready])
  return <div className="platform-page account-page">
    <PageTitle title="个人账号" description="管理个人资料、账号安全与上传令牌。" />
    {error && <Alert type="error" message={error} />}
    <div className="account-identity-summary"><Avatar size={48} className="account-avatar">{Array.from(user?.display_name ?? user?.username ?? 'U')[0]}</Avatar><div className="account-identity-copy"><strong>{user?.display_name}</strong><span>@{user?.username}</span></div><Tag>{user?.role === 'admin' ? '管理员' : '普通用户'}</Tag></div>
    <div className="account-sections">
    <Card title="基本资料"><p className="account-section-note">显示名用于标识你的上传记录和团队操作。</p><Form layout="vertical" initialValues={{ display_name: user?.display_name }} onFinish={async values => {
      try { await authRequest('/auth/me', { method: 'PATCH', body: JSON.stringify(values) }); setIdentity(await authRequest<LoginIdentity>('/auth/me')) } catch (failure) { setError(String(failure)) }
    }}><Form.Item label="用户名"><Input value={user?.username} disabled /></Form.Item><Form.Item label="显示名" name="display_name" rules={[{ required: true, whitespace: true }]}><Input maxLength={128} /></Form.Item><Button type="primary" htmlType="submit">保存资料</Button></Form></Card>
    <Card title="账号安全"><PasswordForm onChanged={() => {}} /><div className="account-security-exit"><p className="account-section-note">退出当前浏览器的登录会话。</p><LogoutButton /></div></Card>
    </div>
    <TokensPanel />
  </div>
}

export function AdminUsersPage() {
  const ready = useSessionReady()
  const [rows, setRows] = useState<UserIdentity[]>([])
  const [q, setQ] = useState('')
  const [error, setError] = useState('')
  const [temporary, setTemporary] = useState('')
  useEffect(() => { if (!ready) setTemporary('') }, [ready])
  const load = useCallback(async () => { try { setRows(await authRequest<UserIdentity[]>(`/admin/users?q=${encodeURIComponent(q)}&limit=500`)) } catch (failure) { setError(String(failure)) } }, [q])
  useEffect(() => { void load() }, [load])
  const update = async (id: string, patch: object) => {
    try { await authRequest(`/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }); await load() }
    catch (failure) { setError(String(failure)) }
  }
  return <div className="platform-page admin-page">
    <PageTitle title="账号管理" description="管理团队账号、角色与 CI 上传凭据。" />
    {error && <Alert type="error" message={error} />}
    <Card className="admin-accounts-card"><Input.Search className="admin-toolbar" aria-label="搜索账号" placeholder="查找用户名或显示名" onSearch={setQ} allowClear />
    <Table<UserIdentity> rowKey="id" dataSource={rows} scroll={{ x: 820 }} columns={[
      { title: '用户名', dataIndex: 'username' }, { title: '显示名', dataIndex: 'display_name' },
      { title: '角色', render: (_, row) => row.kind === 'human' ? <Select value={row.role} options={[{ value: 'member', label: '普通用户' }, { value: 'admin', label: '管理员' }]} onChange={role => void update(row.id, { role })} /> : row.kind },
      { title: '状态', render: (_, row) => row.enabled ? '启用' : '禁用' },
      { title: '操作', render: (_, row) => ['human', 'service'].includes(row.kind) && <Space><Button onClick={() => void update(row.id, { enabled: !row.enabled })}>{row.enabled ? '禁用' : '启用'}</Button>{row.kind === 'human' && <Button onClick={async () => { try { const result = await authRequest<{ temporary_password: string }>(`/admin/users/${row.id}:reset-password`, { method: 'POST' }); setTemporary(result.temporary_password) } catch (failure) { setError(String(failure)) } }}>重置密码</Button>}</Space> },
    ]} /></Card>
    <TokensPanel service />
    <Modal title="一次性临时密码" open={ready && !!temporary} onCancel={() => setTemporary('')} onOk={() => setTemporary('')} destroyOnHidden><Input readOnly value={temporary} /><Typography.Paragraph>请交给对应用户。首次登录必须修改密码。</Typography.Paragraph></Modal>
  </div>
}
