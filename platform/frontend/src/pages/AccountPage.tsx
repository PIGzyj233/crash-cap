import { Alert, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { authRequest, clearIdentity, setIdentity, type LoginIdentity, type UserIdentity } from '../api/authTransport'
import { PasswordForm, useIdentity } from '../components/Authentication'

type Token = { id: string; name: string; expires_at: string; revoked_at: string | null; last_used_at: string | null }
export function TokensPanel({ service = false }: { service?: boolean }) {
  const root = service ? '/admin/service-users/usr_ci/tokens' : '/me/tokens'
  const [rows, setRows] = useState<Token[]>([])
  const [secret, setSecret] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const refresh = useCallback(async () => { try { setRows(await authRequest<Token[]>(root)) } catch (failure) { setError(String(failure)) } }, [root])
  useEffect(() => { void refresh() }, [refresh])
  return <Card title={service ? 'CI 上传令牌' : '个人 CLI 上传令牌'}>
    <Typography.Paragraph>令牌仅可上传文件和查询上传结果。原文只显示一次；有效期默认 90 天。</Typography.Paragraph>
    {error && <Alert type="error" message={error} />}
    <Form layout="inline" initialValues={{ expires_in_days: 90 }} onFinish={async values => {
      setBusy(true); setError('')
      try { const result = await authRequest<{ token: string }>(root, { method: 'POST', body: JSON.stringify(values) }); setSecret(result.token); await refresh() }
      catch (failure) { setError(String(failure)) } finally { setBusy(false) }
    }}>
      <Form.Item name="name" label="用途" rules={[{ required: true, whitespace: true }]}><Input placeholder="例如 nightly-build" maxLength={128} /></Form.Item>
      <Form.Item name="expires_in_days" label="有效天数"><InputNumber min={1} max={365} /></Form.Item>
      <Button htmlType="submit" type="primary" loading={busy}>创建令牌</Button>
    </Form>
    <Table<Token> rowKey="id" dataSource={rows} style={{ marginTop: 20 }} columns={[
      { title: '名称', dataIndex: 'name' }, { title: '到期时间', dataIndex: 'expires_at', render: value => new Date(value).toLocaleString() },
      { title: '状态', render: (_, row) => row.revoked_at ? <Tag>已撤销</Tag> : new Date(row.expires_at) < new Date() ? <Tag>已过期</Tag> : <Tag color="green">有效</Tag> },
      { title: '操作', render: (_, row) => <Button disabled={!!row.revoked_at} onClick={async () => { try { await authRequest(`${root}/${row.id}:revoke`, { method: 'POST' }); await refresh() } catch (failure) { setError(String(failure)) } }}>撤销</Button> },
    ]} />
    <Modal title="保存令牌，此窗口关闭后无法再次查看" open={!!secret} onCancel={() => setSecret('')} onOk={() => setSecret('')} destroyOnHidden>
      <Input.TextArea aria-label="新令牌" readOnly value={secret} autoSize />
      <Typography.Paragraph>将它保存到 CI 的 CRASHCAP_TOKEN 密钥变量，或保存到文件并使用 --token-file。不会自动写入浏览器存储。</Typography.Paragraph>
    </Modal>
  </Card>
}

export function AccountPage() {
  const user = useIdentity()
  const [error, setError] = useState('')
  return <Space direction="vertical" size="large" style={{ width: '100%' }}>
    <Typography.Title level={2}>个人账号</Typography.Title>
    {error && <Alert type="error" message={error} />}
    <Card title={user?.username}><Form layout="inline" initialValues={{ display_name: user?.display_name }} onFinish={async values => {
      try { await authRequest('/auth/me', { method: 'PATCH', body: JSON.stringify(values) }); setIdentity(await authRequest<LoginIdentity>('/auth/me')) } catch (failure) { setError(String(failure)) }
    }}><Form.Item label="显示名" name="display_name" rules={[{ required: true, whitespace: true }]}><Input maxLength={128} /></Form.Item><Button htmlType="submit">保存</Button></Form></Card>
    <TokensPanel />
    <Card title="修改密码"><PasswordForm onChanged={() => {}} /></Card>
    <Button onClick={async () => { try { await authRequest('/auth/logout', { method: 'POST' }); clearIdentity() } catch (failure) { setError(String(failure)) } }}>退出登录</Button>
  </Space>
}

export function AdminUsersPage() {
  const [rows, setRows] = useState<UserIdentity[]>([])
  const [q, setQ] = useState('')
  const [error, setError] = useState('')
  const [temporary, setTemporary] = useState('')
  const load = useCallback(async () => { try { setRows(await authRequest<UserIdentity[]>(`/admin/users?q=${encodeURIComponent(q)}&limit=500`)) } catch (failure) { setError(String(failure)) } }, [q])
  useEffect(() => { void load() }, [load])
  const update = async (id: string, patch: object) => {
    try { await authRequest(`/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }); await load() }
    catch (failure) { setError(String(failure)) }
  }
  return <Space direction="vertical" size="large" style={{ width: '100%' }}>
    <Typography.Title level={2}>账号管理</Typography.Title>
    {error && <Alert type="error" message={error} />}
    <Input.Search placeholder="查找用户名或显示名" onSearch={setQ} allowClear />
    <Table<UserIdentity> rowKey="id" dataSource={rows} columns={[
      { title: '用户名', dataIndex: 'username' }, { title: '显示名', dataIndex: 'display_name' },
      { title: '角色', render: (_, row) => row.kind === 'human' ? <Select value={row.role} options={[{ value: 'member', label: '普通用户' }, { value: 'admin', label: '管理员' }]} onChange={role => void update(row.id, { role })} /> : row.kind },
      { title: '状态', render: (_, row) => row.enabled ? '启用' : '禁用' },
      { title: '操作', render: (_, row) => ['human', 'service'].includes(row.kind) && <Space><Button onClick={() => void update(row.id, { enabled: !row.enabled })}>{row.enabled ? '禁用' : '启用'}</Button>{row.kind === 'human' && <Button onClick={async () => { try { const result = await authRequest<{ temporary_password: string }>(`/admin/users/${row.id}:reset-password`, { method: 'POST' }); setTemporary(result.temporary_password) } catch (failure) { setError(String(failure)) } }}>重置密码</Button>}</Space> },
    ]} />
    <TokensPanel service />
    <Modal title="一次性临时密码" open={!!temporary} onCancel={() => setTemporary('')} onOk={() => setTemporary('')} destroyOnHidden><Input readOnly value={temporary} /><Typography.Paragraph>请交给对应用户。首次登录必须修改密码。</Typography.Paragraph></Modal>
  </Space>
}
