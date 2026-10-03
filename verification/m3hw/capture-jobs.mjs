/** M3HW: capture the Jobs module scrolled to named jobs (FL-183/FL-184 runs walked before the
 * walk scrolled its capture). usage: node capture-jobs.mjs <app-url> <out.png> <job-name-prefix> */
import { createRequire } from 'node:module'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const [base, target, prefix] = process.argv.slice(2)
const context = await chromium.launchPersistentContext('/private/tmp/m3hw-final-capture-profile', {
  channel: 'chrome', headless: true, viewport: { width: 1600, height: 1000 } })
const page = context.pages()[0] ?? await context.newPage()
await page.goto(base, { waitUntil: 'domcontentloaded' })
await page.getByRole('button', { name: 'Library', exact: true }).click()
const add = page.getByRole('button', { name: 'Add Jobs', exact: true })
if (await add.count() && await add.isEnabled()) await add.click()
await page.getByRole('button', { name: 'Library', exact: true }).click()
if (await page.getByRole('button', { name: 'Sheet', exact: true }).getAttribute('aria-pressed') !== 'true')
  await page.getByRole('button', { name: 'Sheet', exact: true }).click()
await page.waitForTimeout(5000)
const handle = page.locator('[data-testid="rack-plugin-frame-jobs"]')
await handle.scrollIntoViewIfNeeded()
await page.frameLocator('[data-testid="rack-plugin-frame-jobs"]').getByText(`${prefix} scheduled`).scrollIntoViewIfNeeded()
await page.waitForTimeout(1500)
await handle.screenshot({ path: target })
await context.close()
