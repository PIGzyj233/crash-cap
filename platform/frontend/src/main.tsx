import React from 'react'
import ReactDOM from 'react-dom/client'
import { ApiProvider } from './api/context'
import { createApiClient } from './api/client'
import { createMockApiClient, parseMockScenario } from './api/mock'
import { App } from './App'
import { BrowserRouter } from 'react-router-dom'
import './styles.css'

const useMock = import.meta.env.VITE_USE_MOCK !== 'false'
const mockScenario = parseMockScenario(new URLSearchParams(window.location.search).get('__mock'))
const api = useMock ? createMockApiClient({ scenario: mockScenario }) : createApiClient()

// antd's <App> lives inside <ConfigProvider> (in App.tsx) so that message,
// notification and modal inherit the brand theme instead of antd defaults.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ApiProvider api={api}>
      <BrowserRouter><App /></BrowserRouter>
    </ApiProvider>
  </React.StrictMode>,
)
