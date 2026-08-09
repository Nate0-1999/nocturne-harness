import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import './assets/base.css'
import './assets/shell.css'
import './assets/rack.css'

const isRackModuleDocument = new URLSearchParams(globalThis.location.search).has('rack_module')
document.documentElement.toggleAttribute('data-rack-module-document', isRackModuleDocument)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
