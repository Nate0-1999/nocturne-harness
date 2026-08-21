import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { applyTheme, DEFAULT_THEME, loadTheme, themeFromSearch } from './themes'
import './themes/plate.generated.css'
import './themes/themes.css'
import './assets/base.css'
import './assets/shell.css'
import './assets/rack.css'
import './themes/materials.css'
import './themes/grimoire.generated.css'

const isRackModuleDocument = new URLSearchParams(globalThis.location.search).has('rack_module')
document.documentElement.toggleAttribute('data-rack-module-document', isRackModuleDocument)
const initialTheme = isRackModuleDocument
  ? themeFromSearch(globalThis.location.search) ?? DEFAULT_THEME
  : loadTheme(globalThis.localStorage)
applyTheme(initialTheme)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
