/** One context capture of the current build on the test palace, for rows this packet's diff
 * touches but does not walk (the M3PL precedent): the whole Sheet with every module this packet
 * changed on it. usage: node context.mjs <app-url> <out.png> */
import { createRequire } from 'node:module'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const [base, target] = process.argv.slice(2)
const context = await chromium.launchPersistentContext('/private/tmp/m3hw-work/walk-profile', {
  channel: 'chrome', headless: true, viewport: { width: 1600, height: 1000 },
  args: ['--use-angle=metal', '--enable-unsafe-webgpu'],
})
const page = context.pages()[0] ?? await context.newPage()
await page.goto(base, { waitUntil: 'domcontentloaded' })
await page.getByRole('button', { name: 'Library', exact: true }).click()
for (const name of ['Farm', 'Roots', 'Palace', 'Security', 'Jobs']) {
  const add = page.getByRole('button', { name: `Add ${name}`, exact: true })
  if (await add.count() && await add.isEnabled()) await add.click()
}
await page.getByRole('button', { name: 'Library', exact: true }).click()
if (await page.getByRole('button', { name: 'Sheet', exact: true }).getAttribute('aria-pressed') !== 'true')
  await page.getByRole('button', { name: 'Sheet', exact: true }).click()
await page.waitForTimeout(10000)
await page.screenshot({ path: target, fullPage: true })
await context.close()
