// FIXTURE driver: serves the frame-rate fixture only for this check's lifetime, headless, 60 Hz display cap.
import { createRequire } from 'node:module'
import { resolve } from 'node:path'
const require = createRequire(new URL('../package.json', import.meta.url))
const { createServer } = await import(require.resolve('vite'))
const { chromium } = require('playwright-core')
const [feed = '/m3vl-dev/feed.json', tier = 'efficient', module = 'roots'] = process.argv.slice(2)
const server = await createServer({ root: resolve(import.meta.dirname, '..'), logLevel: 'error', server: { port: 0 } })
await server.listen()
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--ignore-gpu-blocklist', ...(process.env.UNCAPPED ? ['--disable-gpu-vsync', '--disable-frame-rate-limit'] : [])] })
const page = await browser.newPage({ viewport: { width: 1280, height: 600 } })
try {
  await page.goto(`http://localhost:${server.httpServer.address().port}/m3vl-dev/perf.html?feed=${feed}&tier=${tier}&module=${module}`)
  await page.waitForFunction(() => document.querySelector('#measurement')?.textContent?.includes('"complete":true'), null, { timeout: 60000 })
  console.log(await page.locator('#measurement').textContent())
  await page.screenshot({ path: process.env.SHOT ?? '/dev/null' }).catch(() => {})
} finally { await browser.close(); await server.close() }
