export const THEMES = [
  { id: 'neo-noir', label: 'NEO-NOIR' },
  { id: 'seraph-dressed', label: 'SERAPH DRESSED' },
  { id: 'gold-lines', label: 'GOLD LINES' },
] as const

export type ThemeId = (typeof THEMES)[number]['id']

export const DEFAULT_THEME: ThemeId = 'neo-noir'
export const THEME_STORAGE_KEY = 'nocturne.theme.v1'

export function isThemeId(value: unknown): value is ThemeId {
  return THEMES.some((theme) => theme.id === value)
}

export function loadTheme(storage: Pick<Storage, 'getItem'>): ThemeId {
  const stored = storage.getItem(THEME_STORAGE_KEY)
  return isThemeId(stored) ? stored : DEFAULT_THEME
}

export function themeFromSearch(search: string): ThemeId | null {
  const value = new URLSearchParams(search).get('theme')
  return isThemeId(value) ? value : null
}

export function applyTheme(theme: ThemeId, storage?: Pick<Storage, 'setItem'>): void {
  document.documentElement.dataset.theme = theme
  storage?.setItem(THEME_STORAGE_KEY, theme)
}
