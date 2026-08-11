/** PLAN M2UX4 / D.2 113: the named default and persistent alternates are one closed set. */

import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DEFAULT_THEME,
  THEMES,
  THEME_STORAGE_KEY,
  isThemeId,
  loadTheme,
  themeFromSearch,
} from '../src/themes.ts'

/** P2 requires one closed set of three faces with the worn skin as the default. */
test('three theme identities remain closed with NEO-NOIR as the safe default', () => {
  assert.equal(DEFAULT_THEME, 'neo-noir')
  assert.deepEqual(THEMES.map((theme) => theme.id), [
    'neo-noir',
    'seraph-dressed',
    'gold-lines',
  ])
  assert.equal(isThemeId('gold-lines'), true)
  assert.equal(isThemeId('plate-script'), false)
})

/** P2 requires persistence and complete sandboxed-frame selection without a fourth face. */
test('stored theme and iframe query parsing fail closed to the worn default', () => {
  const storage = { getItem: (key) => key === THEME_STORAGE_KEY ? 'seraph-dressed' : null }
  assert.equal(loadTheme(storage), 'seraph-dressed')
  assert.equal(loadTheme({ getItem: () => 'unknown' }), 'neo-noir')
  assert.equal(themeFromSearch('?rack_module=chat&theme=gold-lines'), 'gold-lines')
  assert.equal(themeFromSearch('?theme=unknown'), null)
})
