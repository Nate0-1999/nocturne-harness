/** F073: a busy Palace retries, and only the recovered surface clears its error. */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
const require = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = require('playwright-core')
const [base, evidence] = process.argv.slice(2)
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1650, height: 970 } })
  await page.goto(base)
  const frame = id => page.frameLocator(`[data-testid="rack-plugin-frame-${id}"]`)
  const conversation = frame('conversation')
  const busy = conversation.getByText('The Palace is busy, retrying.', { exact: true })
  await busy.waitFor({ state: 'visible' })
  await page.screenshot({ path: `${evidence}/07-busy-palace-retrying.png` })
  await busy.waitFor({ state: 'hidden' })
  const spend = frame('vitals')
  await spend.getByRole('button', { name: 'Refresh', exact: true }).waitFor()
  assert.equal(await spend.getByText('Detailed spend needs a newer Palace.').count(), 0)
  const calls = await (await fetch(`${base}/__scenario__/failure`)).json()
  assert.ok(calls.spend_table >= 2)
  await fetch(`${base}/__scenario__/failure`, { method: 'POST' })
  await frame('palace_state').getByRole('button', { name: 'Refresh', exact: true }).click()
  const failure = conversation.getByText('The Palace is unavailable. Try again.', { exact: true })
  await failure.waitFor({ state: 'visible' })
  await spend.getByRole('button', { name: 'Refresh', exact: true }).click()
  await spend.getByText('Refreshing…').waitFor({ state: 'hidden' })
  assert.ok(await failure.isVisible(), 'unrelated successful Spend read must not clear curation failure')
  await frame('palace_state').getByRole('button', { name: 'Refresh', exact: true }).click()
  await failure.waitFor({ state: 'hidden' })
  await page.getByTestId('rack-plugin-frame-conversation').scrollIntoViewIfNeeded()
  await page.screenshot({ path: `${evidence}/08-palace-recovered-banner-cleared.png` })
  const result = { startup_429_retried: true, no_version_message: true, unrelated_success_preserves_error: true, recovered_surface_clears_error: true }
  await writeFile(`${evidence}/recovery.json`, JSON.stringify(result, null, 2) + '\n')
  console.log(JSON.stringify(result))
} finally {
  await browser.close()
}
