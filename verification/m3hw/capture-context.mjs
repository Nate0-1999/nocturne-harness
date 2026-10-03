/** M3HW: one current-build Sheet capture per context-only row (F086).
 * usage: node capture-context.mjs <app-url> <out-dir> <row>... */
import { createRequire } from 'node:module'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const [base, out, ...rows] = process.argv.slice(2)
const context = await chromium.launchPersistentContext('/private/tmp/m3hw-final-capture-profile', {
  channel: 'chrome', headless: true, viewport: { width: 1600, height: 1000 },
  args: ['--use-angle=metal', '--enable-unsafe-webgpu'] })
const page = context.pages()[0] ?? await context.newPage()
await page.goto(base, { waitUntil: 'domcontentloaded' })
if (await page.getByRole('button', { name: 'Sheet', exact: true }).getAttribute('aria-pressed') !== 'true')
  await page.getByRole('button', { name: 'Sheet', exact: true }).click()
await page.waitForTimeout(8000)
for (const row of rows) {
  await page.screenshot({ path: `${out}/${row}.png` })
  await page.waitForTimeout(2500)
}
await context.close()
