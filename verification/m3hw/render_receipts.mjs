/** Render terminal receipts as images for rows whose walk is a command line (FL-166).
 * usage: node render_receipts.mjs <out.png> <receipt.txt>... */
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const [target, ...receipts] = process.argv.slice(2)
const escape = (text) => text.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c])
const body = receipts.map((path) => `<pre>${escape(readFileSync(path, 'utf8'))}</pre>`).join('<hr>')
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 400 } })
await page.setContent(`<html><body style="background:#0b0e14;color:#d8dee9;font:13px/1.45 'JetBrains Mono',Menlo,monospace;margin:20px">${body}</body></html>`)
await page.screenshot({ path: target, fullPage: true })
await browser.close()
