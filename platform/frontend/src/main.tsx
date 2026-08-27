import React from 'react'
import ReactDOM from 'react-dom/client'
import { ApiProvider } from './api/context'
import { createApiClient } from './api/client'
import { createMockApiClient } from './api/mock'
import { App } from './App'
import './styles.css'

const useMock = import.meta.env.VITE_USE_MOCK !== 'false'
const api = useMock ? createMockApiClient() : createApiClient()

// antd's <App> lives inside <ConfigProvider> (in App.tsx) so that message,
// notification and modal inherit the brand theme instead of antd defaults.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ApiProvider api={api}>
      <App />
    </ApiProvider>
  </React.StrictMode>,
)
