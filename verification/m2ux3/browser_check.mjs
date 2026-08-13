/** PLAN M2UX3 rendered proof: Vitals drags, edge/corner resizes, and persists. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const evidenceDir = dirname(fileURLToPath(import.meta.url))
const baseUrl = process.argv.includes('--base-url')
  ? process.argv[process.argv.indexOf('--base-url') + 1]
  : 'http://127.0.0.1:8804'
const fixtureUrl = `${baseUrl}/?fixture=${encodeURIComponent('M2UX3 REGRESSION')}`
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()
const consoleProblems = []
const pageErrors = []
const observations = []

page.on('console', (message) => {
  if (message.type() === 'error') consoleProblems.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(error.message))

try {
  await mkdir(evidenceDir, { recursive: true })
  await page.goto(fixtureUrl, { waitUntil: 'domcontentloaded' })
  await waitForRack(page)

  const mountedIds = await page.locator('[data-rack-template-module="true"]').evaluateAll(
    (modules) => modules.map((module) => module.getAttribute('data-rack-module')),
  )
  assertJsonEqual(mountedIds, ['threads', 'chat', 'memory', 'vitals', 'context_bars'])
  observations.push({ mounted_template_modules: mountedIds })

  const vitals = rackModule(page, 'vitals')
  const cursors = {}
  for (const direction of ['w', 'n', 'nw']) {
    const handle = page.getByTestId(`rack-resize-vitals-${direction}`)
    await handle.hover({ force: true })
    await page.waitForTimeout(160)
    const hoverState = await handle.evaluate((element) => ({
      cursor: getComputedStyle(element).cursor,
      opacity: getComputedStyle(element).opacity,
      module_hovered: element.parentElement?.matches(':hover') ?? false,
      handle_hovered: element.matches(':hover'),
    }))
    cursors[direction] = hoverState.cursor
    if (hoverState.opacity !== '1') {
      throw new Error(`${direction} resize handle did not appear on hover: ${JSON.stringify(hoverState)}`)
    }
  }
  assertJsonEqual(cursors, { w: 'ew-resize', n: 'ns-resize', nw: 'nwse-resize' })
  observations.push({ hover_cursors: cursors })

  await dragModule(page, 'vitals', 'context_bars')
  await expectGeometry(page, 'vitals', { x: 4, width: 9, height: 4 })
  observations.push({ after_drag: await geometry(page, 'vitals') })

  const unit = await gridUnit(page)
  await dragHandle(page, 'rack-resize-vitals-w', -unit.x, 0)
  await expectGeometry(page, 'vitals', { x: 3, width: 10, height: 4 })
  await dragHandle(page, 'rack-resize-vitals-n', 0, unit.y * 2)
  await expectGeometry(page, 'vitals', { x: 3, width: 10, height: 2 })
  observations.push({ after_edges: await geometry(page, 'vitals') })
  await page.screenshot({ path: join(evidenceDir, '01-vitals-moved-edge-resized-1280x900.png') })

  await dragHandle(page, 'rack-resize-vitals-nw', unit.x, -unit.y * 2)
  await expectGeometry(page, 'vitals', { x: 4, width: 9, height: 4 })
  observations.push({ after_corner: await geometry(page, 'vitals') })

  await page.reload({ waitUntil: 'domcontentloaded' })
  await waitForRack(page)
  await expectGeometry(page, 'vitals', { x: 4, width: 9, height: 4 })
  const restoredOrder = await page.locator('[data-rack-template-module="true"]').evaluateAll(
    (modules) => modules
      .filter((module) => ['vitals', 'context_bars'].includes(module.getAttribute('data-rack-module') ?? ''))
      .map((module) => module.getAttribute('data-rack-module')),
  )
  assertJsonEqual(restoredOrder, ['context_bars', 'vitals'])
  observations.push({ after_reload: await geometry(page, 'vitals'), restored_order: restoredOrder })
  await page.screenshot({ path: join(evidenceDir, '02-vitals-layout-restored-1280x900.png') })

  if (consoleProblems.length !== 0 || pageErrors.length !== 0) {
    throw new Error(JSON.stringify({ consoleProblems, pageErrors }))
  }
  const evidence = {
    fixture: 'M2UX3 REGRESSION',
    observations,
    console_problems: consoleProblems,
    page_errors: pageErrors,
  }
  await writeFile(
    join(evidenceDir, 'module-template.json'),
    `${JSON.stringify(evidence, null, 2)}\n`,
    'utf8',
  )
  console.log('M2UX3 module template PASS: Vitals drag, edges, corner, and reload')
} finally {
  await context.close()
  await browser.close()
}

async function waitForRack(targetPage) {
  await frame(targetPage, 'header').getByTestId('connection').getByText('Palace ready').waitFor()
  await targetPage.getByTestId('rack-grid').waitFor()
}

async function dragModule(targetPage, sourceId, targetId) {
  const source = rackModule(targetPage, sourceId).locator('.rack-module__drag')
  const target = rackModule(targetPage, targetId).locator('.rack-module__drag')
  const sourceBox = await source.boundingBox()
  const targetBox = await target.boundingBox()
  if (sourceBox === null || targetBox === null) throw new Error('module drag geometry unavailable')
  await targetPage.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2)
  await targetPage.mouse.down()
  await targetPage.mouse.move(targetBox.x + targetBox.width / 2, targetBox.y + targetBox.height / 2, { steps: 8 })
  await targetPage.mouse.up()
}

async function dragHandle(targetPage, testId, deltaX, deltaY) {
  const handle = targetPage.getByTestId(testId)
  const box = await handle.boundingBox()
  if (box === null) throw new Error(`${testId} geometry unavailable`)
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  await targetPage.mouse.move(x, y)
  await targetPage.mouse.down()
  await targetPage.mouse.move(x + deltaX, y + deltaY, { steps: 8 })
  await targetPage.mouse.up()
}

async function gridUnit(targetPage) {
  const box = await targetPage.getByTestId('rack-grid').boundingBox()
  if (box === null) throw new Error('rack grid geometry unavailable')
  return { x: box.width / 12, y: box.height / 12 }
}

async function expectGeometry(targetPage, moduleId, expected) {
  try {
    await targetPage.waitForFunction(
      ({ id, geometry: wanted }) => {
        const module = document.querySelector(`[data-testid="rack-module-${id}"]`)
        return module !== null &&
          Number(module.getAttribute('data-grid-x')) === wanted.x &&
          Number(module.getAttribute('data-grid-width')) === wanted.width &&
          Number(module.getAttribute('data-grid-height')) === wanted.height
      },
      { id: moduleId, geometry: expected },
      { timeout: 3000 },
    )
  } catch {
    throw new Error(
      `${moduleId} geometry expected ${JSON.stringify(expected)}, got ${JSON.stringify(await geometry(targetPage, moduleId))}`,
    )
  }
}

async function geometry(targetPage, moduleId) {
  return rackModule(targetPage, moduleId).evaluate((module) => ({
    x: Number(module.getAttribute('data-grid-x')),
    width: Number(module.getAttribute('data-grid-width')),
    height: Number(module.getAttribute('data-grid-height')),
  }))
}

function rackModule(targetPage, moduleId) {
  return targetPage.getByTestId(`rack-module-${moduleId}`)
}

function frame(targetPage, moduleId) {
  return targetPage.frameLocator(`iframe[data-testid="rack-plugin-frame-${moduleId}"]`)
}

function assertJsonEqual(actual, expected) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`)
  }
}
