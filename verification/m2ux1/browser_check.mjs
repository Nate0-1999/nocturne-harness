/** PLAN M2ST4 and SPEC B.6 r12 keep the complete rendered Rack sweep standing. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { auditLayout, LAYOUT_SWEEP_WIDTHS } from '../../web/src/layoutAudit.ts'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const evidenceDir = parseOutputDir(args)
const baseUrl = parseBaseUrl(args)
const widths = parseWidths(args)
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()
const consoleProblems = []
const pageErrors = []
const evidence = {
  base_url: baseUrl,
  widths,
  data_bearing: null,
  states: [],
  console_problems: consoleProblems,
  page_errors: pageErrors,
}

page.on('console', (message) => {
  if (message.type() === 'error') consoleProblems.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(error.message))

await page.addInitScript(installCanvasTextAudit)

try {
  await mkdir(evidenceDir, { recursive: true })
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await waitForRack(page)
  evidence.data_bearing = await assertDataBearingState(page)

  for (const width of widths) {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 })
    await resetRack(page)
    evidence.states.push(await assertCleanState(page, width, 'factory'))
    await openModule(page, 'model_device')
    evidence.states.push(await assertCleanState(page, width, 'model_device'))
    await resetRack(page)

    if (width === 390) {
      await headerFrame(page).getByRole('button', { name: 'Threads' })
        .evaluate((element) => element.click())
      evidence.states.push(await assertCleanState(page, width, 'threads-drawer'))
      await page.screenshot({
        path: join(evidenceDir, '02-thread-title-mobile-390x844.png'),
      })
      await resetRack(page)
    }
    if (width === 1280) {
      await page.screenshot({
        path: join(evidenceDir, '01-fixed-desktop-1280x900.png'),
      })
    }
    if (width === 1920) {
      await page.screenshot({
        path: join(evidenceDir, '03-ultrawide-1920x900.png'),
      })
    }

    for (const moduleId of ['palace_queue', 'memory_graph', 'injection_console', 'thread_end']) {
      await openModule(page, moduleId)
      evidence.states.push(await assertCleanState(page, width, moduleId))
      await resetRack(page)
    }
  }

  if (consoleProblems.length !== 0 || pageErrors.length !== 0) {
    throw new Error(`browser diagnostics were not clean: ${JSON.stringify({ consoleProblems, pageErrors })}`)
  }
  await writeFile(
    join(evidenceDir, 'rendered-sweep.json'),
    `${JSON.stringify(evidence, null, 2)}\n`,
    'utf8',
  )
  console.log(`M2UX1 rendered sweep PASS: ${evidence.states.length} states`)
} finally {
  await context.close()
  await browser.close()
}

async function waitForRack(targetPage) {
  await headerFrame(targetPage).getByTestId('connection').getByText('Link live').waitFor({ state: 'attached' })
  await targetPage.getByTestId('stage-viewport').waitFor()
}

async function resetRack(targetPage) {
  await targetPage.reload({ waitUntil: 'domcontentloaded' })
  await waitForRack(targetPage)
  const workTab = targetPage.getByRole('tab', { name: 'Work' })
  if ((await workTab.getAttribute('aria-selected')) !== 'true') {
    await workTab.click()
    await targetPage.reload({ waitUntil: 'domcontentloaded' })
    await waitForRack(targetPage)
  }
}

async function openModule(targetPage, moduleId) {
  if (moduleId === 'palace_queue') {
    await headerFrame(targetPage).getByRole('button', { name: 'Palace queue' })
      .evaluate((element) => element.click())
  } else if (moduleId === 'memory_graph') {
    await targetPage.getByRole('tab', { name: 'Graph' }).click()
  } else if (moduleId === 'injection_console') {
    await targetPage.getByRole('tab', { name: 'Injection' }).click()
  } else if (moduleId === 'model_device') {
    const modelControl = frame(targetPage, 'chat').locator('button[aria-label^="Active model:"]')
    await modelControl.waitFor()
    await modelControl.evaluate((element) => element.click())
  } else if (moduleId === 'thread_end') {
    await frame(targetPage, 'threads').getByRole('button', { name: /^Archive / })
      .evaluate((element) => element.click())
  }
  await targetPage.getByTestId(`rack-plugin-frame-${moduleId}`).waitFor()
}

async function assertCleanState(targetPage, width, state) {
  console.log(`M2UX1 audit ${width}px ${state}`)
  const nodes = await collectNodes(targetPage)
  const result = auditLayout(nodes)
  if (
    result.collisions.length !== 0 ||
    result.clipped.length !== 0 ||
    result.text_collisions.length !== 0
  ) {
    throw new Error(JSON.stringify({
      width,
      state,
      collisions: result.collisions.map((item) => ({
        first: `${item.first.scope}:${item.first.label}`,
        second: `${item.second.scope}:${item.second.label}`,
        width: item.overlap_width,
        height: item.overlap_height,
      })),
      clipped: result.clipped.map((item) => `${item.scope}:${item.label}`),
      text_collisions: result.text_collisions.map((item) => ({
        first: `${item.first.scope}:${item.first.label}`,
        second: `${item.second.scope}:${item.second.label}`,
        width: item.overlap_width,
        height: item.overlap_height,
      })),
    }, null, 2))
  }
  return { width, state, interactive: nodes.filter((node) => node.interactive).length, text: nodes.length }
}

async function collectNodes(targetPage) {
  const nodes = await collectDocumentNodes(targetPage, 'shell', 0, 0)
  for (const childFrame of targetPage.frames().filter((candidate) => candidate !== targetPage.mainFrame())) {
    const frameElement = await childFrame.frameElement()
    const box = await frameElement.boundingBox()
    const inert = await frameElement.evaluate((element) => Boolean(element.closest('[inert]')))
    if (box === null || inert) continue
    const frameSize = await frameElement.evaluate((element) => ({
      width: element.clientWidth,
      height: element.clientHeight,
    }))
    const url = new URL(childFrame.url())
    const scope = url.searchParams.get('rack_module') ?? 'unknown-module'
    nodes.push(...await collectDocumentNodes(
      childFrame,
      scope,
      box.x,
      box.y,
      frameSize.width > 0 ? box.width / frameSize.width : 1,
      frameSize.height > 0 ? box.height / frameSize.height : 1,
    ))
  }
  nodes.push(...await collectCanvasTextNodes(targetPage))
  return nodes
}

async function collectDocumentNodes(target, scope, offsetX, offsetY, scaleX = 1, scaleY = 1) {
  return target.locator('body').evaluate((body, options) => {
    const interactiveSelector = [
      'a[href]',
      'button:not(:disabled)',
      'input:not([type="hidden"]):not(:disabled)',
      'select:not(:disabled)',
      'textarea:not(:disabled)',
      'summary',
      '[tabindex]:not([tabindex="-1"])',
    ].join(',')
    const visible = (element) => {
      const style = getComputedStyle(element)
      const rect = element.getBoundingClientRect()
      return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0 &&
        rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
        rect.left < innerWidth && rect.top < innerHeight &&
        element.closest('.visually-hidden') === null &&
        element.closest('[aria-hidden="true"], [inert]') === null
    }
    const candidates = [...body.querySelectorAll('*')].filter((element) => {
      const directText = [...element.childNodes].some(
        (node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? '').trim() !== '',
      )
      return element.matches(interactiveSelector) || directText
    })
    const visualSurfaces = [...body.querySelectorAll('svg')]
    const clippedRect = (element) => {
      const raw = element.getBoundingClientRect()
      let left = Math.max(raw.left, 0)
      let top = Math.max(raw.top, 0)
      let right = Math.min(raw.right, innerWidth)
      let bottom = Math.min(raw.bottom, innerHeight)
      for (let ancestor = element.parentElement; ancestor !== null; ancestor = ancestor.parentElement) {
        const style = getComputedStyle(ancestor)
        const ancestorRect = ancestor.getBoundingClientRect()
        if (['auto', 'hidden', 'clip', 'scroll'].includes(style.overflowX)) {
          left = Math.max(left, ancestorRect.left)
          right = Math.min(right, ancestorRect.right)
        }
        if (['auto', 'hidden', 'clip', 'scroll'].includes(style.overflowY)) {
          top = Math.max(top, ancestorRect.top)
          bottom = Math.min(bottom, ancestorRect.bottom)
        }
      }
      return right > left && bottom > top ? { left, top, right, bottom } : null
    }
    return candidates.filter(visible).flatMap((element, index) => {
      const rect = clippedRect(element)
      if (rect === null) return []
      const label = (
        element.getAttribute('aria-label') ??
        element.getAttribute('data-testid') ??
        element.textContent ??
        element.tagName
      ).trim().replace(/\s+/gu, ' ').slice(0, 100)
      return [{
        id: `${options.scope}-${index}`,
        label,
        scope: options.scope,
        rect: {
          x: rect.left * options.scaleX + options.offsetX,
          y: rect.top * options.scaleY + options.offsetY,
          width: (rect.right - rect.left) * options.scaleX,
          height: (rect.bottom - rect.top) * options.scaleY,
        },
        interactive: element.matches(interactiveSelector),
        clipped: !(element instanceof SVGElement) && element.clientWidth > 0 &&
          element.scrollWidth > element.clientWidth + 1,
        text_renderer: element instanceof SVGTextElement ? 'svg' : 'dom',
        text_surface: element instanceof SVGTextElement
          ? `${options.scope}:svg-${visualSurfaces.indexOf(element.ownerSVGElement)}`
          : undefined,
      }]
    })
  }, { scope, offsetX, offsetY, scaleX, scaleY })
}

async function collectCanvasTextNodes(targetPage) {
  const nodes = []
  for (const candidateFrame of targetPage.frames()) {
    const offset = candidateFrame === targetPage.mainFrame()
      ? { x: 0, y: 0 }
      : await candidateFrame.frameElement().then((element) => element.boundingBox())
    if (offset === null) continue
    const scope = candidateFrame === targetPage.mainFrame()
      ? 'shell'
      : new URL(candidateFrame.url()).searchParams.get('rack_module') ?? 'unknown-module'
    const frameNodes = await candidateFrame.evaluate((options) => {
      const records = globalThis.__nocturneCanvasTextAudit ?? []
      const seen = new Set()
      const canvases = [...document.querySelectorAll('canvas')]
      return records.flatMap((record, index) => {
        if (!(record.canvas instanceof HTMLCanvasElement) || !record.canvas.isConnected) return []
        const canvasRect = record.canvas.getBoundingClientRect()
        const scaleX = canvasRect.width / record.canvas.width
        const scaleY = canvasRect.height / record.canvas.height
        const key = [record.text, record.x, record.y, record.width, record.height].join(':')
        if (seen.has(key)) return []
        seen.add(key)
        return [{
          id: `${options.scope}-canvas-${index}`,
          label: record.text.slice(0, 100),
          scope: options.scope,
          rect: {
            x: canvasRect.x + record.x * scaleX + options.offsetX,
            y: canvasRect.y + record.y * scaleY + options.offsetY,
            width: record.width * scaleX,
            height: record.height * scaleY,
          },
          interactive: false,
          clipped: false,
          text_renderer: 'canvas',
          text_surface: `${options.scope}:canvas-${canvases.indexOf(record.canvas)}`,
        }]
      })
    }, { scope, offsetX: offset.x, offsetY: offset.y })
    nodes.push(...frameNodes)
  }
  return nodes
}

async function assertDataBearingState(targetPage) {
  await frame(targetPage, 'vitals').getByText('Ledger drift · -$0.08').waitFor()
  await targetPage.getByRole('tab', { name: 'Graph' }).click()
  await frame(targetPage, 'memory_graph').locator('.graph-node').first().waitFor()
  const graphNodes = await frame(targetPage, 'memory_graph').locator('.graph-node').count()
  if (graphNodes < 2) throw new Error(`data-bearing graph needs multiple nodes, got ${graphNodes}`)
  await targetPage.getByRole('tab', { name: 'Work' }).click()
  return { spend: 'Ledger drift · -$0.08', graph_nodes: graphNodes }
}

function installCanvasTextAudit() {
  const records = []
  Object.defineProperty(globalThis, '__nocturneCanvasTextAudit', {
    configurable: false,
    value: records,
  })
  for (const method of ['fillText', 'strokeText']) {
    const original = CanvasRenderingContext2D.prototype[method]
    CanvasRenderingContext2D.prototype[method] = function patchedText(text, x, y, maxWidth) {
      const metrics = this.measureText(String(text))
      const width = Math.min(metrics.width, maxWidth ?? metrics.width)
      const ascent = metrics.actualBoundingBoxAscent || Number.parseFloat(this.font) || 10
      const descent = metrics.actualBoundingBoxDescent || 2
      const left = this.textAlign === 'center'
        ? x - width / 2
        : this.textAlign === 'right' || this.textAlign === 'end'
          ? x - width
          : x
      records.push({
        canvas: this.canvas,
        text: String(text),
        x: left,
        y: y - ascent,
        width,
        height: ascent + descent,
      })
      return original.call(this, text, x, y, maxWidth)
    }
  }
}

function headerFrame(targetPage) {
  return frame(targetPage, 'header')
}

function frame(targetPage, moduleId) {
  return targetPage.frameLocator(`iframe[data-testid="rack-plugin-frame-${moduleId}"]`)
}

function parseBaseUrl(args) {
  const index = args.indexOf('--base-url')
  return index === -1 ? 'http://127.0.0.1:8801' : args[index + 1]
}

function parseWidths(args) {
  const index = args.indexOf('--width')
  if (index === -1) return [...LAYOUT_SWEEP_WIDTHS]
  const width = Number(args[index + 1])
  if (!LAYOUT_SWEEP_WIDTHS.includes(width)) {
    throw new Error(`--width must be one of ${LAYOUT_SWEEP_WIDTHS.join(', ')}`)
  }
  return [width]
}

function parseOutputDir(args) {
  const index = args.indexOf('--evidence-dir')
  return index === -1
    ? dirname(fileURLToPath(import.meta.url))
    : resolve(args[index + 1])
}
