import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { createApiClient } from './api/client'
import { ApiProvider } from './api/context'
import { App } from './App'
import './styles.css'

const api = createApiClient()

// antd's <App> lives inside <ConfigProvider> (in App.tsx) so that message,
// notification and modal inherit the brand theme instead of antd defaults.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ApiProvider api={api}>
      <BrowserRouter><App /></BrowserRouter>
    </ApiProvider>
  </React.StrictMode>,
)
