/** M3HW: a module capture beside its plate. usage: node side.mjs <module.png> <plate.png> <out.png> <caption> */
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
const require = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = require('playwright-core')
const [left, right, out, caption] = process.argv.slice(2)
const b64 = (p) => `data:image/png;base64,${readFileSync(p).toString('base64')}`
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1600, height: 700 } })
await page.setContent(`<body style="margin:0;background:#05070b;color:#ccd;font:14px Menlo,monospace"><div style="display:flex;gap:12px;padding:12px"><figure style="margin:0;flex:1"><img src="${b64(left)}" style="width:100%"><figcaption>module (this build)</figcaption></figure><figure style="margin:0;flex:1"><img src="${b64(right)}" style="width:100%"><figcaption>plate</figcaption></figure></div><p style="padding:0 12px">${caption}</p></body>`)
await page.screenshot({ path: out, fullPage: true })
await browser.close()
