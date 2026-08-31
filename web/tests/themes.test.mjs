/** PLAN M2UX4-M2UX6 / D.2 113-119: curated built-ins stay closed; pressed data may join them. */

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

/** P2 and D.2 115 require the five curated themes with NEO-NOIR still worn by default. */
test('five theme identities remain closed with NEO-NOIR as the safe default', () => {
  assert.equal(DEFAULT_THEME, 'neo-noir')
  assert.deepEqual(THEMES.map((theme) => theme.id), [
    'neo-noir',
    'seraph-dressed',
    'gold-lines',
    'wizard-mode',
    'technomancer',
  ])
  assert.equal(isThemeId('gold-lines'), true)
  assert.equal(isThemeId('wizard-mode'), true)
  assert.equal(isThemeId('technomancer'), true)
  assert.equal(isThemeId(`pressed-${'a'.repeat(16)}`), true)
  assert.equal(isThemeId('plate-script'), false)
})

/** P2 and D.2 114 require persistence to fail closed when pressed token data is absent. */
test('stored theme and iframe query parsing fail closed to the worn default', () => {
  const storage = { getItem: (key) => key === THEME_STORAGE_KEY ? 'seraph-dressed' : null }
  assert.equal(loadTheme(storage), 'seraph-dressed')
  assert.equal(loadTheme({ getItem: () => 'unknown' }), 'neo-noir')
  assert.equal(loadTheme({ getItem: () => `pressed-${'a'.repeat(16)}` }), 'neo-noir')
  assert.equal(themeFromSearch('?rack_module=conversation&theme=gold-lines'), 'gold-lines')
  assert.equal(themeFromSearch('?rack_module=conversation&theme=wizard-mode'), 'wizard-mode')
  assert.equal(themeFromSearch(`?theme=pressed-${'a'.repeat(16)}`), `pressed-${'a'.repeat(16)}`)
  assert.equal(themeFromSearch('?theme=unknown'), null)
})
