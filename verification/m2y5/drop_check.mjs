/** M2Y5 rendered regression: a dropped Markdown file uses the real queue path. */

import { createRequire } from 'node:module'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const browser = await chromium.launch({ channel: 'chrome', headless: true })

try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  await page.goto('http://127.0.0.1:8765/', { waitUntil: 'domcontentloaded' })
  const header = page.frameLocator('iframe[title="Nocturne Header"]')
  await header.getByRole('button', { name: 'Palace queue' }).click()
  const queue = page.frameLocator('iframe[title="Palace Queue"]')
  await queue.locator('.seed-drop').waitFor()
  await queue.locator('.seed-drop').evaluate((target) => {
    const transfer = new DataTransfer()
    transfer.items.add(new File([
      '# Drop path\n\nA dropped seed remains pending until its batch is approved.',
    ], 'dropped-seed.md', { type: 'text/markdown' }))
    target.dispatchEvent(new DragEvent('drop', { bubbles: true, dataTransfer: transfer }))
  })
  await queue.getByText('Split complete. Review each document as one batch.').waitFor({
    timeout: 120_000,
  })
  await queue.getByText('dropped-seed.md').waitFor()
  console.log('M2Y5 drop PASS: dropped-seed.md is waiting for explicit batch review')
} finally {
  await browser.close()
}
