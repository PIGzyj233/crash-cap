import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { createApiClient } from './api/client'
import { ApiProvider } from './api/context'
import { Authentication } from './components/Authentication'
import { App } from './App'
import { ApplicationTheme } from './theme/ApplicationTheme'
import './styles.css'

const api = createApiClient()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ApplicationTheme><BrowserRouter><Authentication><ApiProvider api={api}><App /></ApiProvider></Authentication></BrowserRouter></ApplicationTheme>
  </React.StrictMode>,
)
