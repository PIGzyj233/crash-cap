import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button, Result } from 'antd'

/**
 * Catches render errors so a single bad page cannot blank the whole app.
 *
 * Mounted twice: once inside ConfigProvider (so the fallback is themed) and
 * once around the routed content, keyed by page identity — the inner one is
 * what keeps the shell and navigation usable when one page throws.
 *
 * Deliberately logs only the message and component stack. Report payloads may
 * contain source text or module data, which must never reach the console.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode; onReset?: () => void },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[crash-cap] render error:', error.message, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    const reset = () => {
      this.setState({ error: null })
      this.props.onReset?.()
    }
    return (
      <Result
        status="error"
        title="页面渲染失败"
        subTitle="界面遇到未预期的错误；分析数据本身不受影响，可重试或返回。"
        extra={[
          <Button key="retry" type="primary" onClick={reset}>重试</Button>,
          <Button key="reload" onClick={() => window.location.reload()}>刷新页面</Button>,
        ]}
      />
    )
  }
}
