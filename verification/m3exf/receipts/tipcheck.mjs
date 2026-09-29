// M3EX-26 check: leave each control the way a real mouse does (many small moves) vs a jump.
import { createRequire } from 'node:module'
const require = createRequire('/private/tmp/m3exf-work/harness/web/package.json')
const { chromium } = require('playwright-core')
const [url, out] = process.argv.slice(2)
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
for (const steps of [1, 25]) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  await page.goto(url); await sleep(5000)
  await page.getByRole('button', { name: 'Sheet', exact: true }).click(); await sleep(2500)
  const row = page.frameLocator('[data-testid="rack-plugin-frame-threads"]').locator('li button, [data-thread-id]').first()
  const box = await row.boundingBox()
  await page.mouse.move(box.x + 40, box.y + 10, { steps })
  await sleep(600)
  const send = page.frameLocator('[data-testid="rack-plugin-frame-conversation"]').getByRole('button', { name: /transmit/i })
  const sbox = await send.boundingBox()
  await page.mouse.move(sbox.x + 10, sbox.y + 10, { steps }); await sleep(600)
  await page.mouse.move(720, 890, { steps }); await sleep(900)
  await page.screenshot({ path: `${out}-steps${steps}.png` })
  await context.close()
}
await browser.close()
