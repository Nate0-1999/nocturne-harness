/** M3FX/P2: a fixture can never present itself as the owner app. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const baseUrl = args.includes('--base-url')
  ? args[args.indexOf('--base-url') + 1]
  : 'http://127.0.0.1:8873'
const fixture = args.includes('--fixture')
  ? args[args.indexOf('--fixture') + 1]
  : 'SYM13 REGRESSION'
const evidenceDir = args.includes('--evidence-dir')
  ? resolve(args[args.indexOf('--evidence-dir') + 1])
  : resolve('verification/m3fx')
const packetId = fixture.split(' ', 1)[0]
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()

try {
  await mkdir(evidenceDir, { recursive: true })
  const response = await page.goto(`${baseUrl}/?fixture=${encodeURIComponent(fixture)}`, {
    waitUntil: 'domcontentloaded',
  })
  if (response === null || !response.ok()) {
    throw new Error(`fixture document did not load: ${response?.status() ?? 'no response'}`)
  }
  if (response.headers()['x-nocturne-fixture'] !== fixture) {
    throw new Error('fixture response lost its server-owned identity header')
  }
  if (response.headers()['x-nocturne-fixture-packet'] !== packetId) {
    throw new Error('fixture response lost its server-owned packet header')
  }

  const curtain = page.locator('#nocturne-fixture-curtain')
  await curtain.waitFor({ state: 'visible' })
  const rendered = await curtain.evaluate((element) => {
    const style = getComputedStyle(element)
    return {
      text: element.textContent?.replace(/\s+/gu, ' ').trim(),
      fixture: element.getAttribute('data-fixture'),
      packetId: element.getAttribute('data-packet-id'),
      position: style.position,
      pointerEvents: style.pointerEvents,
      zIndex: Number(style.zIndex),
    }
  })
  const expectedText = `FIXTURE · ${fixture} · PACKET ${packetId} · NOT THE OWNER APP`
  if (
    rendered.text !== expectedText
    || rendered.fixture !== fixture
    || rendered.packetId !== packetId
    || rendered.position !== 'fixed'
    || rendered.pointerEvents !== 'none'
    || rendered.zIndex < 2147483647
  ) {
    throw new Error(`fixture curtain is not unmistakable: ${JSON.stringify(rendered)}`)
  }

  await page.screenshot({ path: resolve(evidenceDir, 'fixture-curtain.png') })
  await writeFile(
    resolve(evidenceDir, 'fixture-curtain.json'),
    `${JSON.stringify({ fixture, packet_id: packetId, rendered }, null, 2)}\n`,
    'utf8',
  )
  console.log(`M3FX fixture curtain PASS: ${fixture} (${packetId})`)
} finally {
  await context.close()
  await browser.close()
}
