/** M3MD: the model browser and chip in every built-in theme (the look law: every theme keeps
 * working). Read-only: opens the selected thread's Model Device; changes nothing. */

import { createRequire } from 'node:module'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const baseUrl = process.argv[2]
const out = resolve(process.argv[3])
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  for (const theme of ['neo-noir', 'seraph-dressed', 'gold-lines', 'wizard-mode', 'technomancer']) {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
    await context.addInitScript((value) => localStorage.setItem('nocturne.theme.v1', value), theme)
    const page = await context.newPage()
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Sheet', exact: true }).click()
    const conversation = page.frameLocator('[data-testid="rack-plugin-frame-conversation"]')
    await conversation.getByTestId('active-model').click()
    const device = page.frameLocator('[data-testid="rack-plugin-frame-model_device"]')
    await device.locator('[data-testid="model-browser-list"] li').nth(20).waitFor()
    await page.mouse.move(4, 600)
    await page.waitForTimeout(800)
    await page.screenshot({ path: resolve(out, `model-browser-${theme}.png`) })
    await context.close()
  }
} finally {
  await browser.close()
}
