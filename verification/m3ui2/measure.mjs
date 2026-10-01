/** PLAN M3UI2 / FL-201: one scale, measured. Walks every layer's Sheet on the fixture and tables each
 * rendered icon's size and each text run's family / size / weight, per module frame.
 * usage: node verification/m3ui2/measure.mjs --base-url <url> [--fixture <identity>] --out <file.json>
 *        [--theme <id>] [--table <file.md>] [--shots <dir>: one capture per module, same framing every run] */

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
const fixture = args.includes('--fixture') ? argument('--fixture') : null
const out = argument('--out')
const theme = args.includes('--theme') ? argument('--theme') : null
const shots = args.includes('--shots') ? argument('--shots') : null

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage()
await page.goto(fixture === null ? baseUrl : `${baseUrl}/?fixture=${encodeURIComponent(fixture)}`, { waitUntil: 'domcontentloaded' })
await page.getByTestId('rack-plugin-frame-conversation').first().waitFor({ state: 'attached' })
await page.waitForTimeout(1500)
// Every module on a layer, in the Sheet (unscaled): shelved modules return to their layer, the Recipe joins Graph.
await page.evaluate((chosen) => {
  if (chosen !== null) localStorage.setItem('nocturne.theme.v1', chosen)
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
}, theme)
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
    const tag = element.tagName.toLowerCase()
    const role = element.closest('.visually-hidden') !== null ? 'hidden'
      : element.closest('[role="tooltip"], .control-tooltip') !== null ? (tag === 'strong' ? 'tip title' : 'tip detail')
      : tag === 'h1' || element.matches('header > h2, .thread-rail__header h2, .memory-panel__header h2') ? 'module header'
      : /^h[2-4]$/.test(tag) ? 'section head'
      : element.closest('thead') !== null || tag === 'dt' ? 'column head / stat label'
      : element.closest('button, summary, select, [role="tab"]') !== null
        ? (document.documentElement.hasAttribute('data-rack-module-document') ? 'control' : 'frame chrome control')
      : element.closest('label, legend') !== null ? 'field label'
      : tag === 'small' || tag === 'figcaption' ? 'caption'
      : ['dd', 'td', 'output', 'code', 'pre'].includes(tag) ? 'value'
      : tag === 'p' || tag === 'li' ? 'body'
      : 'classed run'
    texts.push({
      role, where: path(element), family: style.fontFamily.split(',')[0].replaceAll('"', '').trim(),
      size: Math.round(parseFloat(style.fontSize) * 100) / 100, weight: style.fontWeight,
      transform: style.textTransform, spacing: style.letterSpacing, sample: own.slice(0, 40),
    })
  }
  // The tells (charge step 3) and the boxes (step 2), as things a script can see.
  const tells = []
  const rootSize = parseFloat(getComputedStyle(document.documentElement).fontSize)
  for (const element of document.querySelectorAll('body *')) {
    if (element.closest('svg, .visually-hidden') !== null || !visible(element)) continue
    const style = getComputedStyle(element)
    const box = element.getBoundingClientRect()
    const bordered = ['Top', 'Right', 'Bottom', 'Left'].filter((side) => parseFloat(style[`border${side}Width`]) > 0 && style[`border${side}Style`] !== 'none')
    const painted = bordered.length > 0 || (style.backgroundColor !== 'rgba(0, 0, 0, 0)' && style.backgroundColor !== 'transparent') || style.backgroundImage !== 'none'
    const radius = parseFloat(style.borderTopLeftRadius)
    const tell = (kind) => tells.push({ kind, where: path(element), sample: (element.innerText ?? '').trim().slice(0, 30) })
    if (radius > 0 && painted) tell(radius >= Math.min(box.width, box.height) / 2 - 1 ? 'pill-or-round' : 'rounded')
    if (style.backdropFilter !== 'none' && style.backdropFilter !== '') tell('glass')
    if (bordered.length === 1 && bordered[0] === 'Left' && parseFloat(style.borderLeftWidth) >= 2) tell('accent-bar')
    if (style.textAlign === 'center' && [...element.childNodes].some((node) => node.nodeType === 3 && node.textContent.trim() !== '') && element.closest('button, th, td') === null) tell('centered-text')
    if (/radial-gradient/.test(style.backgroundImage)) tell('gradient-blob')
    if (/\p{Extended_Pictographic}/u.test([...element.childNodes].filter((node) => node.nodeType === 3).map((node) => node.textContent).join(''))) tell('emoji')
    const interactive = element.closest('button, a, summary, select, input, textarea, label, [role="button"], [role="tab"]') !== null
    const glyphOnly = element.children.length <= 1 && (element.innerText ?? '').trim().length <= 2
      && (element.querySelector('svg') !== null || (element.innerText ?? '').trim().length > 0)
    if (!interactive && bordered.length === 4 && glyphOnly && box.width <= 2.5 * rootSize && box.height <= 2.5 * rootSize) tell('boxed-marker')
  }
  return { icons, texts, tells }
}

/** The evidence table: each reused icon's sizes, then each text role's family / size / weight, by module. */
function table(measured) {
  const icons = new Map()
  const roles = new Map()
  const note = (map, key, style, moduleId) => {
    if (!map.has(key)) map.set(key, new Map())
    if (!map.get(key).has(style)) map.get(key).set(style, new Set())
    map.get(key).get(style).add(moduleId)
  }
  for (const documents of Object.values(measured.layers)) {
    for (const [moduleId, found] of Object.entries(documents)) {
      for (const icon of found.icons) {
        if (icon.icon.startsWith('lucide-')) note(icons, icon.icon.slice(7), `${icon.width} × ${icon.height}`, moduleId)
      }
      for (const text of found.texts) {
        if (text.role !== 'hidden') note(roles, text.role, `${text.family} · ${text.size}px · ${text.weight}${text.transform === 'uppercase' ? ' · caps' : ''}`, moduleId)
      }
    }
  }
  const rows = (map) => [...map.entries()].sort(([a], [b]) => a.localeCompare(b)).flatMap(([key, styles]) =>
    [...styles.entries()].sort(([, a], [, b]) => b.size - a.size)
      .map(([style, modules]) => `| ${key} | ${style} | ${[...modules].sort().join(', ')} |`))
  const tells = new Map()
  for (const documents of Object.values(measured.layers)) {
    for (const [moduleId, found] of Object.entries(documents)) {
      for (const tell of found.tells) note(tells, tell.kind, tell.where.split(' > ').at(-1), moduleId)
    }
  }
  return [
    `# One scale, measured (${measured.theme ?? 'default theme'}, ${measured.base})`, '',
    `Icon sizes in use: ${[...new Set([...icons.values()].flatMap((styles) => [...styles.keys()]))].join(', ') || 'none'}`, '',
    '| icon | rendered size | modules |', '|---|---|---|', ...rows(icons), '',
    '| text role | family · size · weight | modules |', '|---|---|---|', ...rows(roles), '',
    '| tell the script can see | element | modules |', '|---|---|---|', ...rows(tells), '',
  ].join('\n')
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
if (args.includes('--table')) await writeFile(argument('--table'), table(result), 'utf8')
console.log(Object.entries(result.layers).map(([layer, documents]) => `${layer}: ${Object.keys(documents).join(', ')}`).join('\n'))
await browser.close()
