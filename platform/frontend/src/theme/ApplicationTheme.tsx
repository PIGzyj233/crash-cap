import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import type { ReactNode } from 'react'
import { antdTheme } from './antdTheme'

/** Theme and feedback must also be available before and after authentication. */
export function ApplicationTheme({ children }: { children: ReactNode }) {
  return <ConfigProvider theme={antdTheme} locale={zhCN}><AntApp>{children}</AntApp></ConfigProvider>
}
