/**
 * M2B rendered regression: exercise the real daemon, sandboxed rack bridge,
 * H5 memory gate, grid layout controls, and true 390x844 responsive shell.
 */

import { createRequire } from 'node:module'
import { copyFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const evidenceDir = dirname(fileURLToPath(import.meta.url))
const h5Trace = join(evidenceDir, '../h5/trace.jsonl')
const baseUrl = parseBaseUrl(process.argv.slice(2))
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const evidence = { base_url: baseUrl, modes: {} }

try {
  evidence.modes.desktop = await runMode('desktop', { width: 1440, height: 900 })
  evidence.modes.mobile = await runMode('mobile', { width: 390, height: 844 })
  await writeFile(
    join(evidenceDir, 'rendered-scripted.json'),
    `${JSON.stringify(evidence, null, 2)}\n`,
    'utf8',
  )
  console.log(`M2B rendered PASS: ${join(evidenceDir, 'rendered-scripted.json')}`)
} finally {
  await browser.close()
}

async function runMode(mode, viewport) {
  let seeded = false
  let cleanup = null
  const context = await browser.newContext({ viewport, screen: viewport, deviceScaleFactor: 1 })
  const page = await context.newPage()
  const consoleProblems = []
  const pageErrors = []
  const framePolicies = []
  page.on('console', (message) => {
    if (message.type() === 'warning' || message.type() === 'error') {
      consoleProblems.push({ type: message.type(), text: message.text() })
    }
  })
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('response', (response) => {
    if (response.url().includes('rack.localhost') && response.url().includes('rack_module=')) {
      framePolicies.push({
        url: response.url(),
        csp: response.headers()['content-security-policy'] ?? null,
      })
    }
  })

  try {
    await fetchJson(`${baseUrl}/__scenario__/seed`, { method: 'POST' })
    seeded = true
    const expectation = await fetchJson(`${baseUrl}/__scenario__/expectation`)
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
    await waitForRack(page)

    const result = {
      viewport,
      sandbox: await sandboxEvidence(page),
      arrival: await renderedGeometry(page),
      console_problems: consoleProblems,
      page_errors: pageErrors,
      screenshots: {},
    }
    assertCommonArrival(result, mode)

    if (mode === 'desktop') {
      result.screenshots.factory = await capture(
        page,
        '01-factory-desktop-1440x900.png',
      )
      result.layout = await exerciseDesktopLayout(page)
      await typeAndSend(page, expectation.first_prompt)
      await waitForGate(page)
      result.gate = await gateEvidence(page)
      result.screenshots.gate = await capture(
        page,
        '02-custom-gate-desktop-1440x900.png',
      )
      result.gate_scroll = await exerciseGateScroll(page)
      result.screenshots.gate_scrolled = await capture(
        page,
        '02b-custom-gate-scrolled-desktop-1440x900.png',
      )
      await continueGate(page)
      await waitForResponse(page, 'H5 deterministic model response 1.')
      result.screenshots.response = await capture(
        page,
        '03-response-desktop-1440x900.png',
      )
      result.hostile_origin = await assertHostileOriginRejected(page)
    } else {
      result.screenshots.arrival = await capture(
        page,
        '04-arrival-mobile-390x844.png',
      )
      result.drawers = await exerciseMobileDrawers(page)
      result.screenshots.threads = await capture(
        page,
        '05-threads-mobile-390x844.png',
      )
      await closeThreadDrawer(page)
      await openMemoryDrawer(page)
      result.screenshots.memory = await capture(
        page,
        '06-memory-mobile-390x844.png',
      )
      await closeMemoryDrawer(page)
      await typeAndSend(page, expectation.first_prompt)
      await waitForGate(page)
      result.gate = await gateEvidence(page)
      result.screenshots.gate = await capture(
        page,
        '07-gate-mobile-390x844.png',
      )
      result.gate_scroll = await exerciseGateScroll(page)
      result.screenshots.gate_scrolled = await capture(
        page,
        '07b-gate-scrolled-mobile-390x844.png',
      )
      await continueGate(page)
      await waitForResponse(page, 'H5 deterministic model response 1.')
      result.screenshots.response = await capture(
        page,
        '08-response-mobile-390x844.png',
      )
      result.final_geometry = await renderedGeometry(page)
      assertMobileGeometry(result.final_geometry)
    }

    result.frame_policies = framePolicies
    assertFramePolicies(framePolicies)
    if (consoleProblems.length !== 0 || pageErrors.length !== 0) {
      throw new Error(`browser diagnostics were not clean: ${JSON.stringify({ consoleProblems, pageErrors })}`)
    }
    return result
  } finally {
    await context.close()
    if (seeded) {
      cleanup = await fetchJson(`${baseUrl}/__scenario__/cleanup`, { method: 'POST' })
      await copyFile(h5Trace, join(evidenceDir, `trace-scripted-${mode}.jsonl`))
      await writeFile(
        join(evidenceDir, `cleanup-scripted-${mode}.json`),
        `${JSON.stringify(cleanup, null, 2)}\n`,
        'utf8',
      )
    }
  }
}

async function waitForRack(page) {
  await frame(page, 'header').getByTestId('connection').getByText('Palace ready').waitFor()
  await frame(page, 'threads').getByTestId('new-thread').waitFor({ state: 'attached' })
  await frame(page, 'chat').getByTestId('composer').waitFor()
  await frame(page, 'memory').locator('.memory-panel').waitFor({ state: 'attached' })
}

async function sandboxEvidence(page) {
  return page.locator('iframe[data-testid^="rack-plugin-frame-"]').evaluateAll((frames) =>
    frames.map((frame) => ({
      testid: frame.getAttribute('data-testid'),
      sandbox: frame.getAttribute('sandbox'),
      origin: new URL(frame.src).origin,
    })),
  )
}

async function renderedGeometry(page) {
  return page.evaluate(() => ({
    viewport: { width: window.innerWidth, height: window.innerHeight },
    document: {
      client_width: document.documentElement.clientWidth,
      scroll_width: document.documentElement.scrollWidth,
    },
    modules: [...document.querySelectorAll('[data-rack-module]')].map((element) => ({
      id: element.getAttribute('data-rack-module'),
      grid_x: Number(element.getAttribute('data-grid-x')),
      grid_width: Number(element.getAttribute('data-grid-width')),
      resize_sequence: Number(element.getAttribute('data-resize-sequence')),
      display: getComputedStyle(element).display,
      rect: {
        x: Math.round(element.getBoundingClientRect().x),
        width: Math.round(element.getBoundingClientRect().width),
        height: Math.round(element.getBoundingClientRect().height),
      },
    })),
  }))
}

function assertCommonArrival(result, mode) {
  const expectedViewport = mode === 'desktop'
    ? { width: 1440, height: 900 }
    : { width: 390, height: 844 }
  assertDeepEqual(result.arrival.viewport, expectedViewport, `${mode} viewport`)
  if (result.sandbox.length !== 4) {
    throw new Error(`${mode} arrival expected four first-party iframe modules`)
  }
  for (const frameRecord of result.sandbox) {
    if (frameRecord.sandbox !== 'allow-scripts allow-same-origin') {
      throw new Error(`unexpected sandbox contract: ${JSON.stringify(frameRecord)}`)
    }
    if (!frameRecord.origin.startsWith('http://rack.localhost:')) {
      throw new Error(`rack module did not use the isolated origin: ${JSON.stringify(frameRecord)}`)
    }
  }
  if (mode === 'desktop') {
    assertLayout(result.arrival.modules, [
      ['threads', 1, 2],
      ['chat', 3, 8],
      ['memory', 11, 2],
    ])
  } else {
    assertMobileGeometry(result.arrival)
  }
}

async function exerciseDesktopLayout(page) {
  const before = await renderedGeometry(page)
  const threadResize = page.getByRole('button', { name: 'Resize Channel Stack' })
  const resizeBox = await threadResize.boundingBox()
  const gridBox = await page.getByTestId('rack-grid').boundingBox()
  if (resizeBox === null || gridBox === null) {
    throw new Error('rack resize geometry was unavailable')
  }
  const unit = gridBox.width / 12
  await page.mouse.move(resizeBox.x + resizeBox.width / 2, resizeBox.y + resizeBox.height / 2)
  await page.mouse.down()
  await page.mouse.move(resizeBox.x + resizeBox.width / 2 + unit, resizeBox.y + resizeBox.height / 2)
  await page.mouse.up()
  await page.waitForFunction(() =>
    document.querySelector('[data-rack-module="threads"]')?.getAttribute('data-grid-width') === '3',
  )
  const previousResizeSequence = moduleRecord(before.modules, 'threads').resize_sequence
  await page.waitForFunction(
    (previous) => Number(
      document.querySelector('[data-rack-module="threads"]')?.getAttribute('data-resize-sequence'),
    ) > previous,
    previousResizeSequence,
  )
  const resized = await renderedGeometry(page)
  assertLayout(resized.modules, [
    ['threads', 1, 3],
    ['chat', 4, 7],
    ['memory', 11, 2],
  ])
  if (moduleRecord(resized.modules, 'threads').resize_sequence <= moduleRecord(before.modules, 'threads').resize_sequence) {
    throw new Error('ResizeObserver did not deliver a new thread-module rectangle')
  }

  await pointerDrag(
    page,
    page.getByRole('button', { name: 'Dock Channel Stack; Alt plus arrow keys also moves it' }),
    page.getByRole('button', { name: 'Dock Memory Palace; Alt plus arrow keys also moves it' }),
  )
  await page.waitForFunction(() =>
    document.querySelector('[data-rack-module="threads"]')?.getAttribute('data-grid-x') === '10',
  )
  const docked = await renderedGeometry(page)
  assertLayout(docked.modules, [
    ['chat', 1, 7],
    ['memory', 8, 2],
    ['threads', 10, 3],
  ])

  await page.getByTestId('layout-save').click()
  if ((await page.getByTestId('layout-status').innerText()).trim().toLowerCase() !== 'saved set') {
    throw new Error('saving the rack set did not expose Saved set')
  }
  await page.getByRole('button', { name: 'Resize Memory Palace' }).press('ArrowRight')
  if ((await page.getByTestId('layout-status').innerText()).trim().toLowerCase() !== 'edited set') {
    throw new Error('editing a saved rack did not expose Edited set')
  }
  await page.getByTestId('layout-restore').click()
  const restored = await renderedGeometry(page)
  assertLayout(restored.modules, [
    ['chat', 1, 7],
    ['memory', 8, 2],
    ['threads', 10, 3],
  ])
  await page.reload({ waitUntil: 'domcontentloaded' })
  await waitForRack(page)
  const reloaded = await renderedGeometry(page)
  assertLayout(reloaded.modules, [
    ['chat', 1, 7],
    ['memory', 8, 2],
    ['threads', 10, 3],
  ])
  return { before, resized, docked, restored, reloaded }
}

async function pointerDrag(page, source, target) {
  const sourceBox = await source.boundingBox()
  const targetBox = await target.boundingBox()
  if (sourceBox === null || targetBox === null) {
    throw new Error('rack pointer-drag geometry was unavailable')
  }
  await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2)
  await page.mouse.down()
  await page.mouse.move(
    targetBox.x + targetBox.width / 2,
    targetBox.y + targetBox.height / 2,
    { steps: 8 },
  )
  await page.mouse.up()
}

async function exerciseMobileDrawers(page) {
  const header = frame(page, 'header')
  await header.getByTestId('mobile-threads').click()
  await page.waitForFunction(() =>
    getComputedStyle(document.querySelector('[data-rack-module="threads"]')).display === 'flex',
  )
  const threads = await renderedGeometry(page)
  if (moduleRecord(threads.modules, 'chat').display !== 'flex') {
    throw new Error('chat should remain rendered behind the inert mobile drawer')
  }
  return { threads }
}

async function closeThreadDrawer(page) {
  await frame(page, 'threads').getByRole('button', { name: 'Close threads' }).click()
  await page.waitForFunction(() =>
    getComputedStyle(document.querySelector('[data-rack-module="threads"]')).display === 'none',
  )
}

async function openMemoryDrawer(page) {
  await frame(page, 'header').getByTestId('mobile-memories').click()
  await page.waitForFunction(() =>
    getComputedStyle(document.querySelector('[data-rack-module="memory"]')).display === 'flex',
  )
}

async function closeMemoryDrawer(page) {
  await frame(page, 'memory').getByRole('button', { name: 'Close memory drawer' }).click()
  await page.waitForFunction(() =>
    getComputedStyle(document.querySelector('[data-rack-module="memory"]')).display === 'none',
  )
}

async function typeAndSend(page, prompt) {
  const chat = frame(page, 'chat')
  await chat.getByTestId('composer').type(prompt)
  await chat.getByTestId('send').click()
}

async function waitForGate(page) {
  await page.getByTestId('rack-plugin-frame-gate').waitFor({ state: 'attached' })
  await frame(page, 'gate').getByTestId('memory-gate').waitFor({ state: 'visible' })
}

async function gateEvidence(page) {
  const hostFrame = page.getByTestId('rack-plugin-frame-gate')
  return {
    sandbox: await hostFrame.getAttribute('sandbox'),
    origin: new URL(await hostFrame.getAttribute('src')).origin,
    visible_cards: await frame(page, 'gate').locator('.memory-card').count(),
    continue_visible: await frame(page, 'gate').getByTestId('memory-gate-continue').isVisible(),
  }
}

async function exerciseGateScroll(page) {
  const gate = frame(page, 'gate')
  const content = gate.locator('.memory-gate__content')
  const before = await content.evaluate((element) => ({
    scroll_top: element.scrollTop,
    client_height: element.clientHeight,
    scroll_height: element.scrollHeight,
  }))
  await content.evaluate((element) => {
    element.scrollTop = element.scrollHeight
  })
  const after = await content.evaluate((element) => ({
    scroll_top: element.scrollTop,
    client_height: element.clientHeight,
    scroll_height: element.scrollHeight,
  }))
  const continueVisible = await gate.getByTestId('memory-gate-continue').isVisible()

  if (before.scroll_height <= before.client_height) {
    throw new Error(`gate body did not expose a scroll range: ${JSON.stringify(before)}`)
  }
  if (after.scroll_top <= before.scroll_top) {
    throw new Error(`gate body did not scroll: ${JSON.stringify({ before, after })}`)
  }
  if (!continueVisible) {
    throw new Error('gate Continue action left the viewport while its body scrolled')
  }

  return { before, after, continue_visible: continueVisible }
}

async function assertHostileOriginRejected(page) {
  const payload = encodeURIComponent(`<!doctype html><body>no bridge<script>
    addEventListener('message', (event) => {
      if (event.data?.type === 'nocturne.rack.connect') {
        document.body.textContent = 'bridge granted'
      }
    })
    parent.postMessage({
      type: 'nocturne.rack.ready',
      version: 1,
      module_id: 'chat'
    }, '*')
  </script>`)
  const source = `data:text/html;charset=utf-8,${payload}`
  await page.getByTestId('rack-plugin-frame-chat').evaluate((element, nextSource) => {
    element.src = nextSource
  }, source)
  const hostile = frame(page, 'chat').locator('body')
  await hostile.getByText('no bridge', { exact: true }).waitFor()
  await page.waitForTimeout(300)
  const rendered = (await hostile.innerText()).trim()
  if (rendered !== 'no bridge') {
    throw new Error(`mismatched-origin frame received the rack bridge: ${rendered}`)
  }
  return { attempted_origin: 'null', bridge_granted: false }
}

async function continueGate(page) {
  await frame(page, 'gate').getByTestId('memory-gate-continue').click()
  await page.getByTestId('rack-plugin-frame-gate').waitFor({ state: 'detached' })
}

async function waitForResponse(page, text) {
  await frame(page, 'chat').getByText(text, { exact: true }).waitFor({ state: 'visible' })
}

function frame(page, moduleId) {
  return page.frameLocator(`[data-testid="rack-plugin-frame-${moduleId}"]`)
}

function assertLayout(modules, expected) {
  for (const [id, x, width] of expected) {
    const record = moduleRecord(modules, id)
    if (record.grid_x !== x || record.grid_width !== width) {
      throw new Error(`unexpected ${id} layout: ${JSON.stringify(record)}`)
    }
  }
  const total = expected.reduce((sum, [, , width]) => sum + width, 0)
  if (total !== 12) {
    throw new Error(`rack layout did not conserve 12 grid units: ${total}`)
  }
}

function assertMobileGeometry(geometry) {
  assertDeepEqual(geometry.viewport, { width: 390, height: 844 }, 'mobile viewport')
  if (geometry.document.client_width !== 390 || geometry.document.scroll_width !== 390) {
    throw new Error(`mobile document overflowed: ${JSON.stringify(geometry.document)}`)
  }
  if (moduleRecord(geometry.modules, 'header').display !== 'flex') {
    throw new Error('mobile header was not visible')
  }
  if (moduleRecord(geometry.modules, 'chat').display !== 'flex') {
    throw new Error('mobile chat was not visible')
  }
}

function assertFramePolicies(policies) {
  if (policies.length < 4) {
    throw new Error(`expected frame policy responses, received ${policies.length}`)
  }
  for (const policy of policies) {
    if (!policy.csp?.includes("connect-src 'none'")) {
      throw new Error(`rack frame was not network sealed: ${JSON.stringify(policy)}`)
    }
  }
}

function moduleRecord(modules, id) {
  const record = modules.find((module) => module.id === id)
  if (record === undefined) {
    throw new Error(`missing rendered rack module ${id}`)
  }
  return record
}

async function capture(page, filename) {
  const path = join(evidenceDir, filename)
  await page.screenshot({ path })
  return path
}

function assertDeepEqual(actual, expected, label) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${label}: expected ${JSON.stringify(expected)}, received ${JSON.stringify(actual)}`)
  }
}

async function fetchJson(url, init) {
  const response = await fetch(url, init)
  const payload = await response.json()
  if (!response.ok) {
    throw new Error(`${response.status} from ${url}: ${JSON.stringify(payload)}`)
  }
  return payload
}

function parseBaseUrl(args) {
  const index = args.indexOf('--base-url')
  const value = index < 0 ? undefined : args[index + 1]
  if (typeof value !== 'string' || !/^http:\/\/127\.0\.0\.1:\d+$/.test(value)) {
    throw new Error('--base-url must be an http://127.0.0.1:<port> origin')
  }
  return value
}
