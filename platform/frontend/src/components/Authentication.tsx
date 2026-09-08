import { Alert, Button, Card, Form, Input, Spin, Typography } from 'antd'
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { authRequest, clearIdentity, currentUser, enableAuthentication, setIdentity, watchSessionChanges, type LoginIdentity, type UserIdentity } from '../api/authTransport'
import { Brand } from './Brand'
import { LogoutButton } from './LogoutButton'

const IdentityContext = createContext<UserIdentity | null>(null)
const SessionReadyContext = createContext(true)
export function useIdentity() { return useContext(IdentityContext) }
export function useSessionReady() { return useContext(SessionReadyContext) }

function PasswordForm({ onChanged, temporary = false }: { onChanged: () => void; temporary?: boolean }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  return <Form layout="vertical" onFinish={async values => {
    setBusy(true); setError('')
    try { await authRequest('/auth/password', { method: 'POST', body: JSON.stringify({ current_password: values.current_password ?? '', new_password: values.new_password }) }); clearIdentity(); onChanged() }
    catch (failure) { setError(failure instanceof Error ? failure.message : '修改失败') }
    finally { setBusy(false) }
  }}>
    {temporary && <Alert type="info" message="请设置自己的密码，临时密码只能使用一次。" />}
    {!temporary && <Form.Item label="当前密码" name="current_password" rules={[{ required: true }]}><Input.Password autoComplete="current-password" /></Form.Item>}
    <Form.Item label="新密码" name="new_password" rules={[{ required: true }, { min: 12, max: 128 }]}><Input.Password autoComplete="new-password" /></Form.Item>
    <Form.Item label="确认新密码" name="confirmation" dependencies={['new_password']} rules={[{ required: true }, ({ getFieldValue }) => ({ validator: (_, value) => value === getFieldValue('new_password') ? Promise.resolve() : Promise.reject(new Error('两次密码不一致')) })]}><Input.Password autoComplete="new-password" /></Form.Item>
    {error && <Alert type="error" message={error} />}
    <Button type="primary" htmlType="submit" loading={busy}>修改密码并重新登录</Button>
  </Form>
}
export { PasswordForm }

export function Authentication({ children }: { children: ReactNode }) {
  const [login, setLogin] = useState<LoginIdentity | null>(null)
  const [retainedUser, setRetainedUser] = useState<UserIdentity | null>(null)
  const [loading, setLoading] = useState(true)
  const [register, setRegister] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const ready = login && !login.user.must_change_password
  const title = login?.user.must_change_password ? '首次登录设置密码' : register ? '创建内网账号' : '登录崩溃分析平台'
  useEffect(() => {
    if (!loading && !ready) { document.title = `${title} · Crash-Cap`; heading.current?.focus({ preventScroll: true }) }
  }, [loading, ready, title])
  useEffect(() => {
    enableAuthentication()
    const stopWatching = watchSessionChanges()
    const onIdentity = (event: Event) => {
      const next = (event as CustomEvent<LoginIdentity | null>).detail
      setLogin(next)
      if (next || !currentUser()) { setError(''); setRegister(false) }
      if (!currentUser() || next?.user.must_change_password) setRetainedUser(null)
      else if (next) setRetainedUser(next.user)
    }
    window.addEventListener('crashcap-identity', onIdentity)
    let cancelled = false
    void authRequest<LoginIdentity>('/auth/me').then(value => { if (!cancelled) setIdentity(value) }).catch(() => {}).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true; stopWatching(); window.removeEventListener('crashcap-identity', onIdentity) }
  }, [])
  if (loading) return <div className="auth-shell"><Spin tip="正在恢复登录状态" size="large"><div className="auth-loading" /></Spin></div>
  return <>
    {retainedUser && <IdentityContext.Provider value={retainedUser}><SessionReadyContext.Provider value={!!ready}><div hidden={!ready} key={retainedUser.id}>{children}</div></SessionReadyContext.Provider></IdentityContext.Provider>}
    {!ready && <main className="auth-shell"><Card className="auth-card">
      <div className="auth-brand"><Brand /></div>
      <Typography.Title ref={heading} level={1} className="auth-title" tabIndex={-1}>{title}</Typography.Title>
      <p className="auth-description">{register ? '创建个人账号，与团队一起跟进崩溃分析。' : '登录后，继续查看项目的崩溃与分析结果。'}</p>
      {login?.user.must_change_password ? <>
        <PasswordForm temporary onChanged={() => setNotice('密码已更新，请重新登录')} />
        <div className="auth-exit"><LogoutButton /><Typography.Paragraph type="secondary">退出后若尚未完成改密，需要重新联系管理员。</Typography.Paragraph></div>
      </> : <Form layout="vertical" requiredMark={false} onFinish={async values => {
        setBusy(true); setError(''); setNotice('')
        try {
          if (register) {
            await authRequest('/auth/register', { method: 'POST', body: JSON.stringify(values) })
            setRegister(false); setNotice('账号已创建，请登录')
          } else {
            const value = await authRequest<LoginIdentity>('/auth/login', { method: 'POST', body: JSON.stringify(values) })
            setIdentity(value)
          }
        } catch (failure) { setError(failure instanceof Error ? failure.message : '操作失败') }
        finally { setBusy(false) }
      }} key={register ? 'register' : 'login'}>
        <Form.Item label="用户名" name="username" rules={[{ required: true }]}><Input autoComplete="username" maxLength={64} /></Form.Item>
        {register && <Form.Item label="显示名" name="display_name" rules={[{ required: true, whitespace: true }]}><Input maxLength={128} /></Form.Item>}
        <Form.Item label="密码" name="password" rules={[{ required: true }, ...(register ? [{ min: 12, max: 128 }] : [])]}><Input.Password autoComplete={register ? 'new-password' : 'current-password'} maxLength={128} /></Form.Item>
        {error && <Alert type="error" message={error} />}{notice && <Alert type="success" message={notice} />}
        <div className="auth-actions"><Button type="primary" htmlType="submit" loading={busy}>{register ? '注册' : '登录'}</Button><Button type="link" onClick={() => { setRegister(!register); setError('') }}>{register ? '返回登录' : '注册账号'}</Button></div>
        {!register && <p className="auth-footer">忘记密码请联系平台管理员。</p>}
      </Form>}
    </Card></main>}
  </>
}
