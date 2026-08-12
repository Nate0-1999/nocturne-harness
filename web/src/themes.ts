import {
  applyColorwayTokens,
  loadColorways,
  type PressedColorway,
} from './platePress.ts'

export const THEMES = [
  { id: 'neo-noir', label: 'NEO-NOIR' },
  { id: 'seraph-dressed', label: 'SERAPH DRESSED' },
  { id: 'gold-lines', label: 'GOLD LINES' },
] as const

export type BuiltinThemeId = (typeof THEMES)[number]['id']
export type PressedThemeId = `pressed-${string}`
export type ThemeId = BuiltinThemeId | PressedThemeId

export const DEFAULT_THEME: ThemeId = 'neo-noir'
export const THEME_STORAGE_KEY = 'nocturne.theme.v1'

export function isThemeId(value: unknown): value is ThemeId {
  return THEMES.some((theme) => theme.id === value) || (
    typeof value === 'string' && /^pressed-[0-9a-f]{16}$/.test(value)
  )
}

export function loadTheme(storage: Pick<Storage, 'getItem'>): ThemeId {
  const stored = storage.getItem(THEME_STORAGE_KEY)
  if (!isThemeId(stored)) return DEFAULT_THEME
  if (!stored.startsWith('pressed-')) return stored
  return loadColorways(storage).some((colorway) => colorway.id === stored) ? stored : DEFAULT_THEME
}

export function themeFromSearch(search: string): ThemeId | null {
  const value = new URLSearchParams(search).get('theme')
  return isThemeId(value) ? value : null
}

export function applyTheme(
  theme: ThemeId,
  storage?: Pick<Storage, 'setItem'>,
  colorway: PressedColorway | null = null,
): void {
  document.documentElement.dataset.theme = theme
  applyColorwayTokens(document.documentElement, colorway)
  storage?.setItem(THEME_STORAGE_KEY, theme)
}
