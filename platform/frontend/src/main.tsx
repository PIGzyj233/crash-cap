import React from 'react'
import ReactDOM from 'react-dom/client'
import { App as AntApp } from 'antd'
import { ApiProvider } from './api/context'
import { createApiClient } from './api/client'
import { createMockApiClient } from './api/mock'
import { App } from './App'
import './styles.css'

const useMock = import.meta.env.VITE_USE_MOCK !== 'false'
const api = useMock ? createMockApiClient() : createApiClient()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ApiProvider api={api}>
      <AntApp>
        <App />
      </AntApp>
    </ApiProvider>
  </React.StrictMode>,
)
