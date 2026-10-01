/** PLAN M3UI2 / FL-201: one scale, measured. Walks every layer's Sheet on the fixture and tables each
 * rendered icon's size and each text run's family / size / weight, per module frame.
 * usage: node verification/m3ui2/measure.mjs --base-url <url> --fixture <identity> --out <file.json>
 *        [--theme <id>] [--shots <dir>: one capture per module, same framing every run] */

import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const argument = (name) => {
  const index = args.indexOf(name)
  if (index < 0 || args[index + 1] === undefined) throw new Error(`missing ${name}`)
  return args[index + 1]
}
const baseUrl = argument('--base-url')
const fixture = argument('--fixture')
const out = argument('--out')
const theme = args.includes('--theme') ? argument('--theme') : null
const shots = args.includes('--shots') ? argument('--shots') : null

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage()
const url = `${baseUrl}/?fixture=${encodeURIComponent(fixture)}${theme === null ? '' : `&theme=${theme}`}`
await page.goto(url, { waitUntil: 'domcontentloaded' })
await page.getByTestId('rack-plugin-frame-conversation').first().waitFor({ state: 'attached' })
await page.waitForTimeout(1500)
// Every module on a layer, in the Sheet (unscaled): shelved modules return to their layer, the Recipe joins Graph.
await page.evaluate(() => {
  const key = Object.keys(localStorage).find((name) => {
    try { return Array.isArray(JSON.parse(localStorage.getItem(name)).layers) } catch { return false }
  })
  const layout = JSON.parse(localStorage.getItem(key))
  for (const layer of layout.layers) {
    layer.modules.push(...layer.removed_modules)
    layer.removed_modules = []
  }
  const graph = layout.layers.find((layer) => layer.layer_id === 'graph')
  graph.modules.push({ ...graph.modules[0], instance_id: 'recipe', module_id: 'recipe' })
  localStorage.setItem(key, JSON.stringify(layout))
  localStorage.setItem('nocturne.stage.sheet-mode.v1', 'true')
})
await page.reload({ waitUntil: 'domcontentloaded' })
await page.getByRole('tab').first().waitFor({ state: 'visible' })
// The fixture curtain is not product surface: out of the photos and the table.
await page.addStyleTag({ content: 'body > aside, .fixture-curtain { display: none !important }' })

/** Runs inside one document: every icon and every element that directly holds text. */
function census() {
  const visible = (element) => {
    const box = element.getBoundingClientRect()
    const style = getComputedStyle(element)
    return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && Number(style.opacity) > 0
  }
  const path = (element) => {
    const parts = []
    for (let node = element; node !== null && node !== document.body && parts.length < 3; node = node.parentElement) {
      const name = typeof node.className === 'string' && node.className.trim() !== ''
        ? `${node.tagName.toLowerCase()}.${node.className.trim().split(/\s+/).join('.')}`
        : node.tagName.toLowerCase()
      parts.unshift(name)
    }
    return parts.join(' > ')
  }
  const icons = [...document.querySelectorAll('svg')].filter(visible).map((svg) => {
    const box = svg.getBoundingClientRect()
    const holder = svg.closest('button, a, summary, [role="button"], select, label')
    const frameOf = (element) => {
      const style = getComputedStyle(element)
      return style.borderTopWidth !== '0px' && style.borderTopStyle !== 'none'
    }
    let boxed = null
    for (let node = svg.parentElement; node !== null && node !== document.body; node = node.parentElement) {
      const nodeBox = node.getBoundingClientRect()
      if (nodeBox.width > box.width * 4 || nodeBox.height > box.height * 4) break
      if (frameOf(node)) { boxed = path(node); break }
    }
    const lucide = [...svg.classList].find((name) => name.startsWith('lucide-'))
    return {
      icon: lucide ?? (svg.getAttribute('class') || 'svg'), width: Math.round(box.width * 100) / 100,
      height: Math.round(box.height * 100) / 100, button: holder !== null, boxed, where: path(svg.parentElement),
    }
  })
  const texts = []
  for (const element of document.querySelectorAll('body *')) {
    if (element.closest('svg') !== null || !visible(element)) continue
    const own = [...element.childNodes].filter((node) => node.nodeType === 3).map((node) => node.textContent.trim()).join(' ').trim()
    if (own === '') continue
    const style = getComputedStyle(element)
    texts.push({
      where: path(element), family: style.fontFamily.split(',')[0].replaceAll('"', '').trim(),
      size: Math.round(parseFloat(style.fontSize) * 100) / 100, weight: style.fontWeight,
      transform: style.textTransform, spacing: style.letterSpacing, sample: own.slice(0, 40),
    })
  }
  return { icons, texts }
}

const result = { base: baseUrl, theme: await page.evaluate(() => document.documentElement.dataset.theme ?? null), layers: {} }
const layerTabs = page.getByRole('tab')
const layerCount = await layerTabs.count()
/** One hover per document, so the tip is on screen when its document is measured. */
async function measure(target) {
  const tipped = target.locator('[data-tooltip]:visible, [data-tooltip-detail]:visible').first()
  if (await tipped.count() > 0) await tipped.hover({ timeout: 2000 }).catch(() => {})
  await page.waitForTimeout(700)
  return target.evaluate(census)
}
for (let index = 0; index < layerCount; index += 1) {
  const tab = layerTabs.nth(index)
  const layer = (await tab.innerText()).trim()
  await tab.click()
  await page.waitForTimeout(4000)
  const documents = { shell: await measure(page.mainFrame()) }
  for (const frame of page.frames()) {
    if (frame === page.mainFrame()) continue
    const moduleId = new URL(frame.url()).searchParams.get('rack_module')
    if (moduleId === null) continue
    const element = await frame.frameElement()
    if (!(await element.isVisible())) continue
    await element.scrollIntoViewIfNeeded()
    if (shots !== null) {
      const framed = page.getByTestId(`rack-module-${moduleId}`)
      await page.mouse.move(0, 0)
      await (await framed.count() > 0 ? framed.first() : element).screenshot({ path: `${shots}/${moduleId}.png` })
    }
    documents[moduleId] = await measure(frame)
  }
  result.layers[layer] = documents
}
await writeFile(out, `${JSON.stringify(result, null, 1)}\n`, 'utf8')
console.log(Object.entries(result.layers).map(([layer, documents]) => `${layer}: ${Object.keys(documents).join(', ')}`).join('\n'))
await browser.close()
