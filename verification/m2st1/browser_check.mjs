/** PLAN M2ST1/M2ST4 and SPEC B.6 r12: camera, layers, removal, recall, and persistence. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const evidenceDir = args.includes('--evidence-dir')
  ? resolve(args[args.indexOf('--evidence-dir') + 1])
  : dirname(fileURLToPath(import.meta.url))
const baseUrl = args.includes('--base-url')
  ? args[args.indexOf('--base-url') + 1]
  : 'http://127.0.0.1:8806'
const fixture = args.includes('--fixture')
  ? args[args.indexOf('--fixture') + 1]
  : 'M2ST1 REGRESSION'
const fixtureUrl = `${baseUrl}/?fixture=${encodeURIComponent(fixture)}`
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

  const factoryModules = await mountedModules(page)
  assertJsonEqual(factoryModules, [
    'threads', 'chat', 'memory', 'vitals', 'context_bars', 'palace_state', 'palace_queue', 'deck',
  ])
  observations.push({ factory_work_modules: factoryModules })

  const cameraBeforeDrag = await activeCamera(page)
  const viewportBox = await page.getByTestId('stage-viewport').boundingBox()
  if (viewportBox === null) throw new Error('stage viewport geometry unavailable')
  const panPoint = await page.getByTestId('stage-viewport').evaluate((viewport) => {
    const rect = viewport.getBoundingClientRect()
    for (let y = rect.bottom - 32; y > rect.top + 32; y -= 32) {
      for (let x = rect.right - 32; x > rect.left + 32; x -= 32) {
        const hit = document.elementFromPoint(x, y)
        if (
          hit?.closest('.stage-canvas') !== null &&
          hit?.closest('[data-rack-module],button,input,select,textarea,a,[role="tab"]') === null
        ) return { x, y }
      }
    }
    return null
  })
  if (panPoint === null) throw new Error('no empty Stage background was available for panning')
  const panX = panPoint.x
  const panY = panPoint.y
  await page.mouse.move(panX, panY)
  await page.mouse.down()
  await page.mouse.move(panX + 90, panY + 45, { steps: 6 })
  await page.mouse.up()
  const cameraAfterDrag = await activeCamera(page)
  if (
    cameraAfterDrag.x - cameraBeforeDrag.x !== 90 ||
    cameraAfterDrag.y - cameraBeforeDrag.y !== 45
  ) throw new Error(`background pan drifted: ${JSON.stringify({ cameraBeforeDrag, cameraAfterDrag })}`)
  observations.push({ background_pan: { before: cameraBeforeDrag, after: cameraAfterDrag } })

  const initialMemory = await geometry(page, 'memory')
  await page.getByTestId('stage-fit').click()
  await page.waitForFunction(() => {
    const output = document.querySelector('[data-testid="stage-zoom"]')
    return output !== null && Number.parseInt(output.textContent ?? '100', 10) < 50
  })
  const wholeStageZoom = await page.getByTestId('stage-zoom').textContent()
  observations.push({ whole_stage_zoom: wholeStageZoom })
  await page.screenshot({ path: join(evidenceDir, '01-whole-stage-1280x900.png') })

  await page.getByRole('tab', { name: 'Graph' }).click()
  await page.getByTestId('rack-module-memory_graph').waitFor()
  await frame(page, 'memory_graph').getByRole('heading', { name: 'Memory Graph' }).waitFor()
  assertJsonEqual(await mountedModules(page), ['memory_graph'])
  if (await page.locator('.rack-overlay-module--instrument').count() !== 0) {
    throw new Error('Graph still mounted as a fixed overlay')
  }
  const initialGraph = await geometry(page, 'memory_graph')
  await page.getByTestId('rack-module-memory_graph').locator('.rack-module__drag').press('Alt+ArrowRight')
  const movedGraph = { ...initialGraph, x: initialGraph.x + 1 }
  await expectGeometry(page, 'memory_graph', movedGraph)

  await page.getByRole('button', { name: 'Remove Memory Graph' }).click()
  assertJsonEqual(await mountedModules(page), [])
  await page.getByTestId('stage-library-toggle').click()
  const graphLibraryRow = page.getByTestId('stage-library').getByRole('listitem').filter({ hasText: 'Memory Graph' })
  await graphLibraryRow.getByRole('button', { name: 'Add' }).click()
  await expectGeometry(page, 'memory_graph', movedGraph)
  await page.getByRole('button', { name: 'Close stage library' }).click()

  await page.getByRole('button', { name: 'Remove Graph layer' }).click()
  await page.getByTestId('rack-module-chat').waitFor()
  await page.getByTestId('stage-library-toggle').click()
  const removedGraphRow = page.getByTestId('stage-library').getByRole('listitem').filter({ hasText: 'Graph' })
  await removedGraphRow.getByRole('button', { name: 'Restore' }).click()
  await expectGeometry(page, 'memory_graph', movedGraph)
  observations.push({ graph_restored: await geometry(page, 'memory_graph') })
  await page.getByRole('button', { name: 'Close stage library' }).click()

  await page.getByRole('tab', { name: 'Work' }).click()
  await expectGeometry(page, 'memory', initialMemory)
  await page.getByRole('button', { name: 'Remove Memory Palace' }).click()
  await page.getByTestId('stage-library-toggle').click()
  const memoryLibraryRow = page.getByTestId('stage-library').getByRole('listitem').filter({ hasText: 'Memory Palace' })
  await memoryLibraryRow.getByRole('button', { name: 'Add' }).click()
  await expectGeometry(page, 'memory', initialMemory)
  await page.getByRole('button', { name: 'Close stage library' }).click()

  const viewport = page.getByTestId('stage-viewport')
  await viewport.dispatchEvent('wheel', { deltaX: 2400, deltaY: 0 })
  const recall = page.getByRole('navigation', { name: 'Off-screen modules' })
  await recall.waitFor()
  const recalledNames = await recall.getByRole('button').allTextContents()
  if (recalledNames.length === 0) throw new Error('off-screen recall stayed empty after panning away')
  await recall.getByRole('button', { name: 'Active Channel' }).click()
  const intersects = await page.getByTestId('rack-module-chat').evaluate((module) => {
    const moduleRect = module.getBoundingClientRect()
    const viewportRect = document.querySelector('[data-testid="stage-viewport"]')?.getBoundingClientRect()
    return viewportRect !== undefined && moduleRect.right > viewportRect.left &&
      moduleRect.left < viewportRect.right && moduleRect.bottom > viewportRect.top &&
      moduleRect.top < viewportRect.bottom
  })
  if (!intersects) throw new Error('recall did not return Active Channel to the viewport')
  observations.push({ offscreen_recall: recalledNames })

  await page.reload({ waitUntil: 'domcontentloaded' })
  await waitForRack(page)
  await expectGeometry(page, 'memory', initialMemory)
  await page.getByRole('tab', { name: 'Graph' }).click()
  await expectGeometry(page, 'memory_graph', movedGraph)
  await page.screenshot({ path: join(evidenceDir, '02-graph-layer-restored-1280x900.png') })

  if (consoleProblems.length !== 0 || pageErrors.length !== 0) {
    throw new Error(JSON.stringify({ consoleProblems, pageErrors }))
  }
  const evidence = {
    fixture,
    observations,
    console_problems: consoleProblems,
    page_errors: pageErrors,
  }
  await writeFile(join(evidenceDir, 'stage.json'), `${JSON.stringify(evidence, null, 2)}\n`, 'utf8')
  console.log('M2ST1 stage PASS: overview, layers, remove/restore, recall, and reload')
} finally {
  await context.close()
  await browser.close()
}

async function waitForRack(targetPage) {
  await frame(targetPage, 'header').getByTestId('connection').getByText('Palace ready').waitFor()
  await targetPage.getByTestId('stage-viewport').waitFor()
}

async function mountedModules(targetPage) {
  return targetPage.locator('[data-rack-template-module="true"]').evaluateAll(
    (modules) => modules.map((module) => module.getAttribute('data-rack-module')),
  )
}

async function activeCamera(targetPage) {
  return targetPage.evaluate(() => {
    const layout = JSON.parse(localStorage.getItem('nocturne.stage.layout.v4'))
    return layout.layers.find((layer) => layer.layer_id === layout.active_layer_id).camera
  })
}

async function expectGeometry(targetPage, moduleId, expected) {
  await targetPage.waitForFunction(
    ({ id, geometry: wanted }) => {
      const module = document.querySelector(`[data-testid="rack-module-${id}"]`)
      return module !== null &&
        Number(module.getAttribute('data-grid-x')) === wanted.x &&
        Number(module.getAttribute('data-grid-y')) === wanted.y &&
        Number(module.getAttribute('data-grid-width')) === wanted.width &&
        Number(module.getAttribute('data-grid-height')) === wanted.height
    },
    { id: moduleId, geometry: expected },
  )
}

async function geometry(targetPage, moduleId) {
  return targetPage.getByTestId(`rack-module-${moduleId}`).evaluate((module) => ({
    x: Number(module.getAttribute('data-grid-x')),
    y: Number(module.getAttribute('data-grid-y')),
    width: Number(module.getAttribute('data-grid-width')),
    height: Number(module.getAttribute('data-grid-height')),
  }))
}

function frame(targetPage, moduleId) {
  return targetPage.frameLocator(`iframe[data-testid="rack-plugin-frame-${moduleId}"]`)
}

function assertJsonEqual(actual, expected) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`)
  }
}
