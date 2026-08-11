/** M2UX1 rendered no-overlap/no-clip sweep across the complete Rack module set. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { auditLayout, LAYOUT_SWEEP_WIDTHS } from '../../web/src/layoutAudit.ts'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const evidenceDir = dirname(fileURLToPath(import.meta.url))
const args = process.argv.slice(2)
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
  states: [],
  console_problems: consoleProblems,
  page_errors: pageErrors,
}

page.on('console', (message) => {
  if (message.type() === 'error') consoleProblems.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(error.message))

try {
  await mkdir(evidenceDir, { recursive: true })
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await waitForRack(page)
  await ensureLongThread(page)

  for (const width of widths) {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 })
    await resetRack(page)
    evidence.states.push(await assertCleanState(page, width, 'factory'))

    if (width === 390) {
      await headerFrame(page).getByRole('button', { name: 'Threads' }).click()
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

    for (const moduleId of ['palace_queue', 'memory_graph', 'injection_console', 'model_device', 'thread_end']) {
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
  await targetPage.getByTestId('rack-grid').waitFor()
}

async function ensureLongThread(targetPage) {
  const thread = threadsFrame(targetPage)
  const expected = 'Explain the mechanical no-overlap and…'
  if (await thread.getByText(expected, { exact: true }).count()) return

  const composer = chatFrame(targetPage).getByTestId('composer')
  await composer.fill(
    'Explain the mechanical no-overlap and no-clipped-text viewport sweep for the owner.',
  )
  await chatFrame(targetPage).getByTestId('send').click()
  await targetPage.getByTestId('rack-plugin-frame-gate').waitFor()
  await frame(targetPage, 'gate').getByRole('button', { name: 'Stop run' }).click()
  await targetPage.getByTestId('rack-plugin-frame-gate').waitFor({ state: 'detached' })
  await thread.getByText(expected, { exact: true }).waitFor()
}

async function resetRack(targetPage) {
  await targetPage.reload({ waitUntil: 'domcontentloaded' })
  await waitForRack(targetPage)
}

async function openModule(targetPage, moduleId) {
  if (moduleId === 'palace_queue') {
    await headerFrame(targetPage).getByRole('button', { name: 'Palace queue' }).click()
  } else if (moduleId === 'memory_graph') {
    await headerFrame(targetPage).getByRole('button', { name: 'Graph' }).click()
  } else if (moduleId === 'injection_console') {
    await headerFrame(targetPage).getByRole('button', { name: 'Injection' }).click()
  } else if (moduleId === 'model_device') {
    await chatFrame(targetPage).locator('button[aria-label^="Active model:"]').click()
  } else if (moduleId === 'thread_end') {
    await chatFrame(targetPage).getByTestId('archive-thread').click()
  }
  await targetPage.getByTestId(`rack-plugin-frame-${moduleId}`).waitFor()
}

async function assertCleanState(targetPage, width, state) {
  console.log(`M2UX1 audit ${width}px ${state}`)
  const nodes = await collectNodes(targetPage)
  const result = auditLayout(nodes)
  if (result.collisions.length !== 0 || result.clipped.length !== 0) {
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
    const url = new URL(childFrame.url())
    const scope = url.searchParams.get('rack_module') ?? 'unknown-module'
    nodes.push(...await collectDocumentNodes(childFrame, scope, box.x, box.y))
  }
  return nodes
}

async function collectDocumentNodes(target, scope, offsetX, offsetY) {
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
    return candidates.filter(visible).map((element, index) => {
      const rect = element.getBoundingClientRect()
      const label = (
        element.getAttribute('aria-label') ??
        element.getAttribute('data-testid') ??
        element.textContent ??
        element.tagName
      ).trim().replace(/\s+/gu, ' ').slice(0, 100)
      return {
        id: `${options.scope}-${index}`,
        label,
        scope: options.scope,
        rect: {
          x: rect.x + options.offsetX,
          y: rect.y + options.offsetY,
          width: rect.width,
          height: rect.height,
        },
        interactive: element.matches(interactiveSelector),
        clipped: !(element instanceof SVGElement) && element.clientWidth > 0 &&
          element.scrollWidth > element.clientWidth + 1,
      }
    })
  }, { scope, offsetX, offsetY })
}

function headerFrame(targetPage) {
  return frame(targetPage, 'header')
}

function threadsFrame(targetPage) {
  return frame(targetPage, 'threads')
}

function chatFrame(targetPage) {
  return frame(targetPage, 'chat')
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
