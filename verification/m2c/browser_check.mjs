/**
 * M2C rendered regression. It owns a visibly bannered fixture process, uses a
 * fresh browser context, and tears both down even when an assertion fails.
 */

import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const evidenceDir = dirname(fileURLToPath(import.meta.url))
const harnessDir = resolve(evidenceDir, '../..')
const python = join(harnessDir, '.venv/bin/python')
let fixtureHome
let baseUrl
let fixture
let browser

try {
  const port = await reservePort()
  baseUrl = `http://127.0.0.1:${port}`
  fixtureHome = await mkdtemp(join(tmpdir(), 'nocturne-m2c-fixture-'))
  fixture = startFixture(port, fixtureHome)
  await waitForFixture(fixture, `${baseUrl}/__scenario__/trace`)
  browser = await chromium.launch({ channel: 'chrome', headless: true })
  const evidence = {
    fixture: 'M2C REGRESSION',
    base_url: baseUrl,
    desktop: await runDesktop(browser),
    mobile: await runMobile(browser),
    trace: await fetchJson(`${baseUrl}/__scenario__/trace`),
  }
  await writeFile(
    join(evidenceDir, 'rendered-scripted.json'),
    `${JSON.stringify(evidence, null, 2)}\n`,
    'utf8',
  )
  await writeFile(
    join(evidenceDir, 'trace-scripted.json'),
    `${JSON.stringify(evidence.trace, null, 2)}\n`,
    'utf8',
  )
  console.log(`M2C rendered PASS: ${join(evidenceDir, 'rendered-scripted.json')}`)
} finally {
  await browser?.close()
  if (fixture !== undefined) {
    await stopFixture(fixture)
  }
  if (fixtureHome !== undefined) {
    await rm(fixtureHome, { recursive: true, force: true })
  }
}

async function runDesktop(browserInstance) {
  const viewport = { width: 1440, height: 900 }
  const context = await browserInstance.newContext({ viewport, screen: viewport })
  const page = await context.newPage()
  const diagnostics = observe(page)
  await installBridgeTrace(page)
  try {
    await fetchJson(`${baseUrl}/__scenario__/vitals/live`, { method: 'POST' })
    await page.goto(`${baseUrl}/?fixture=M2C%20REGRESSION`, { waitUntil: 'domcontentloaded' })
    await waitForVitals(page, false)
    const arrival = await geometry(page)
    assertViewport(arrival, viewport)
    assertFrameBoundary(await frameBoundary(page), diagnostics.framePolicies, 5)
    assertRows(arrival, { panels: 7, vitals: 4 })
    await capture(page, '01-expanded-desktop-1440x900.png')

    const vitals = frame(page, 'vitals')
    const gauges = await gaugeEvidence(vitals)
    await captureLocator(
      vitals.locator('.vitals-strip--expanded'),
      '01b-gauges-tail-desktop-1440x900.png',
    )
    await resetGaugeScroll(vitals)
    const total = vitals.getByRole('button', { name: 'All spend spend lane' })
    const totalLane = total.locator('..')
    const totalTimeline = vitals.getByRole('slider', { name: 'All spend spend timeline' })
    await scrubAt(page, totalTimeline, 0.983)
    await totalLane.locator('.vitals-lane__readout').getByText('$0.004000000000', { exact: true }).waitFor()
    await totalLane.getByText('Partial · 1 line awaiting a price', { exact: true }).waitFor()
    const sharedTimeline = await sharedTimelineEvidence(vitals)
    const partialSelection = await selectionBusEvidence(
      vitals,
      'total',
      '2026-08-02T17:34:00Z',
    )
    if ((await total.getAttribute('aria-pressed')) !== 'true') {
      throw new Error('hover scrub stole focus from the default total lane')
    }
    await capture(page, '02-partial-scrub-desktop-1440x900.png')

    await scrubAt(page, totalTimeline, 1)
    await totalLane.locator('.vitals-lane__readout').getByText('Awaiting price', { exact: true }).waitFor()
    await totalLane.getByText('Partial · 1 line awaiting a price', { exact: true }).waitFor()
    await capture(page, '03-unpriced-desktop-1440x900.png')

    await scrubAt(page, totalTimeline, 0.96)
    await totalLane.locator('.vitals-lane__readout').getByText('$0.035000000000', { exact: true }).waitFor()

    const building = vitals.getByRole('button', { name: 'Building spend lane' })
    await building.click()
    if ((await building.getAttribute('aria-pressed')) !== 'true') {
      throw new Error('click did not focus the selected spend lane')
    }
    if ((await total.getAttribute('aria-pressed')) !== 'false') {
      throw new Error('lane focus was not exclusive')
    }
    const focusSelection = await selectionBusEvidence(
      vitals,
      'purpose:building',
      '2026-08-02T17:33:00Z',
    )
    const focusStyles = await renderedFocusEvidence(page, vitals)
    await capture(page, '04-focus-desktop-1440x900.png')

    const literalUnreported = vitals.getByRole('button', {
      name: 'unreported spend lane',
      exact: true,
    })
    await literalUnreported.click()
    const literalUnreportedSelection = await selectionBusEvidence(
      vitals,
      'model:~unreported',
      '2026-08-02T17:33:00Z',
    )
    const leadingTilde = vitals.getByRole('button', {
      name: '~unreported spend lane',
      exact: true,
    })
    await leadingTilde.click()
    const leadingTildeSelection = await selectionBusEvidence(
      vitals,
      'model:~~unreported',
      '2026-08-02T17:33:00Z',
    )
    await building.click()

    const collapse = page.getByTestId('vitals-collapse')
    const expandedAria = await requireAriaExpanded(collapse, true, 'desktop arrival')
    await collapse.click()
    await vitals.locator('.vitals-strip--collapsed').waitFor()
    const collapsedAria = await requireAriaExpanded(collapse, false, 'desktop collapse')
    const collapsed = await geometry(page)
    assertRows(collapsed, { panels: 10, vitals: 1 })
    assertReallocation(arrival, collapsed, 'collapse')
    await capture(page, '05-collapsed-desktop-1440x900.png')
    await collapse.click()
    await vitals.locator('.vitals-strip--expanded').waitFor()
    const reopenedAria = await requireAriaExpanded(collapse, true, 'desktop reopen')
    if ((await building.getAttribute('aria-pressed')) !== 'true') {
      throw new Error('collapse/reopen discarded lane focus')
    }

    await fetchJson(`${baseUrl}/__scenario__/vitals/failed`, { method: 'POST' })
    await vitals.getByRole('button', { name: 'Refresh' }).click()
    await vitals.getByRole('alert').getByText('Vitals couldn’t refresh. Chat is still available.').waitFor()
    const composer = frame(page, 'chat').getByTestId('composer')
    await composer.fill('Chat remains locally usable')
    if ((await composer.inputValue()) !== 'Chat remains locally usable') {
      throw new Error('Vitals failure disabled Chat')
    }
    await capture(page, '06-failure-isolated-desktop-1440x900.png')

    await fetchJson(`${baseUrl}/__scenario__/vitals/empty`, { method: 'POST' })
    await vitals.getByRole('button', { name: 'Refresh' }).click()
    await vitals.getByText('No spend recorded in this window.', { exact: true }).waitFor()
    await capture(page, '07-empty-desktop-1440x900.png')

    assertDiagnostics(diagnostics)
    if (diagnostics.queryFrames.length === 0 || diagnostics.queryFrames.some((name) => name !== 'main')) {
      throw new Error(`Vitals query escaped the host bridge: ${JSON.stringify(diagnostics.queryFrames)}`)
    }
    return {
      viewport,
      arrival,
      scrub: {
        readout: '$0.004000000000',
        partial: '1 line awaiting a price',
        shared_timeline: sharedTimeline,
      },
      all_unpriced_readout: 'Awaiting price',
      gauges,
      selection_bus: {
        partial: partialSelection,
        focus: focusSelection,
        a029_literal_unreported: literalUnreportedSelection,
        a029_leading_tilde: leadingTildeSelection,
      },
      focus: { lane: 'purpose:building', rendered_styles: focusStyles },
      collapsed,
      collapse_aria: {
        expanded: expandedAria,
        collapsed: collapsedAria,
        reopened: reopenedAria,
      },
      failure_isolated: true,
      empty_window_rendered: true,
      frame_policies: diagnostics.framePolicies,
      query_frames: diagnostics.queryFrames,
      screenshots: [
        '01-expanded-desktop-1440x900.png',
        '01b-gauges-tail-desktop-1440x900.png',
        '02-partial-scrub-desktop-1440x900.png',
        '03-unpriced-desktop-1440x900.png',
        '04-focus-desktop-1440x900.png',
        '05-collapsed-desktop-1440x900.png',
        '06-failure-isolated-desktop-1440x900.png',
        '07-empty-desktop-1440x900.png',
      ],
    }
  } finally {
    await context.close()
  }
}

async function runMobile(browserInstance) {
  const viewport = { width: 390, height: 844 }
  const context = await browserInstance.newContext({
    viewport,
    screen: viewport,
    hasTouch: true,
    isMobile: true,
    deviceScaleFactor: 1,
  })
  const page = await context.newPage()
  const diagnostics = observe(page)
  await installBridgeTrace(page)
  try {
    await fetchJson(`${baseUrl}/__scenario__/vitals/live`, { method: 'POST' })
    await page.goto(`${baseUrl}/?fixture=M2C%20REGRESSION`, { waitUntil: 'domcontentloaded' })
    await waitForVitals(page, true)
    const collapsedVitals = frame(page, 'vitals')
    await requireTextFullyVisible(
      collapsedVitals.getByText('Awaiting price', { exact: true }),
      'mobile collapsed unpriced value',
    )
    await requireTextFullyVisible(
      collapsedVitals.getByText('Partial · 1 line awaiting a price', { exact: true }),
      'mobile collapsed partial-price copy',
    )
    const arrival = await geometry(page)
    assertViewport(arrival, viewport)
    assertRows(arrival, { panels: 10, vitals: 1 })
    assertFrameBoundary(await frameBoundary(page), diagnostics.framePolicies, 5)
    await capture(page, '08-collapsed-mobile-390x844.png')

    const collapse = page.getByTestId('vitals-collapse')
    const arrivalAria = await requireAriaExpanded(collapse, false, 'mobile arrival')
    await collapse.click()
    const vitals = frame(page, 'vitals')
    await vitals.locator('.vitals-strip--expanded').waitFor()
    const expandedAria = await requireAriaExpanded(collapse, true, 'mobile expand')
    const expanded = await geometry(page)
    assertViewport(expanded, viewport)
    assertRows(expanded, { panels: 7, vitals: 4 })
    assertReallocation(arrival, expanded, 'expand')
    await vitals.getByText('Created', { exact: true }).waitFor()
    const composerBox = await frame(page, 'chat').getByTestId('composer').boundingBox()
    if (composerBox === null || composerBox.y < 0 || composerBox.y + composerBox.height > viewport.height) {
      throw new Error(`mobile expansion hid the composer: ${JSON.stringify(composerBox)}`)
    }
    await capture(page, '09-expanded-mobile-390x844.png')
    const gauges = await gaugeEvidence(vitals)
    await capture(page, '09b-gauges-mobile-390x844.png')
    await resetGaugeScroll(vitals)

    const total = vitals.getByRole('button', { name: 'All spend spend lane' })
    const totalLane = total.locator('..')
    const totalTimeline = vitals.getByRole('slider', { name: 'All spend spend timeline' })
    const totalBox = await totalTimeline.locator('svg').boundingBox()
    if (totalBox === null) {
      throw new Error('mobile total lane had no rendered bounds')
    }
    await page.touchscreen.tap(totalBox.x + totalBox.width * 0.983, totalBox.y + totalBox.height / 2)
    await totalLane.locator('.vitals-lane__readout').getByText('$0.004000000000', { exact: true }).waitFor()
    await totalLane.getByText('Partial · 1 line awaiting a price', { exact: true }).waitFor()
    const sharedTimeline = await sharedTimelineEvidence(vitals)
    const partialSelection = await selectionBusEvidence(
      vitals,
      'total',
      '2026-08-02T17:34:00Z',
    )
    await capture(page, '10-shared-scrub-bottom-mobile-390x844.png')
    if ((await total.getAttribute('aria-pressed')) !== 'true') {
      throw new Error('touch scrub lost the current total focus')
    }
    const building = vitals.getByRole('button', { name: 'Building spend lane' })
    await building.press('Enter')
    if ((await building.getAttribute('aria-pressed')) !== 'true') {
      throw new Error('keyboard lane activation failed on the mobile rack')
    }
    const focusSelection = await selectionBusEvidence(
      vitals,
      'purpose:building',
      '2026-08-02T17:34:00Z',
    )
    const focusStyles = await renderedFocusEvidence(page, vitals)
    await capture(page, '10-touch-focus-mobile-390x844.png')

    await collapse.click()
    await vitals.locator('.vitals-strip--collapsed').waitFor()
    const focusCollapsedAria = await requireAriaExpanded(
      collapse,
      false,
      'mobile focus collapse',
    )
    await collapse.click()
    await vitals.locator('.vitals-strip--expanded').waitFor()
    const reopenedAria = await requireAriaExpanded(collapse, true, 'mobile focus reopen')
    if ((await building.getAttribute('aria-pressed')) !== 'true') {
      throw new Error('mobile collapse/reopen discarded lane focus')
    }
    await building.scrollIntoViewIfNeeded()
    const reopenedFocusStyles = await renderedFocusEvidence(page, vitals)
    await capture(page, '10b-focus-reopened-mobile-390x844.png')

    await fetchJson(`${baseUrl}/__scenario__/vitals/failed`, { method: 'POST' })
    await vitals.getByRole('button', { name: 'Refresh' }).click()
    await vitals.getByRole('alert').waitFor()
    const composer = frame(page, 'chat').getByTestId('composer')
    await composer.fill('Mobile Chat remains locally usable')
    if ((await composer.inputValue()) !== 'Mobile Chat remains locally usable') {
      throw new Error('mobile Vitals failure disabled Chat')
    }
    await collapse.click()
    await vitals.locator('.vitals-strip--collapsed').waitFor()
    const failureCollapsedAria = await requireAriaExpanded(
      collapse,
      false,
      'mobile failure collapse',
    )
    await requireTextFullyVisible(
      vitals.getByRole('alert').getByText('Vitals couldn’t refresh. Chat is still available.'),
      'mobile collapsed failure copy',
    )
    await capture(page, '11-failure-visible-mobile-390x844.png')

    assertDiagnostics(diagnostics)
    if (diagnostics.queryFrames.length === 0 || diagnostics.queryFrames.some((name) => name !== 'main')) {
      throw new Error(`mobile Vitals query escaped the host bridge: ${JSON.stringify(diagnostics.queryFrames)}`)
    }
    return {
      viewport,
      arrival,
      expanded,
      composer_reachable: true,
      failure_chat_usable: true,
      touch_scrub_readout: '$0.004000000000 · partial',
      shared_timeline: sharedTimeline,
      selection_bus: { partial: partialSelection, focus: focusSelection },
      keyboard_focus: 'purpose:building',
      rendered_focus: focusStyles,
      focus_survived_collapse: true,
      reopened_focus: reopenedFocusStyles,
      collapse_aria: {
        arrival: arrivalAria,
        expanded: expandedAria,
        focus_collapsed: focusCollapsedAria,
        reopened: reopenedAria,
        failure_collapsed: failureCollapsedAria,
      },
      gauges,
      collapsed_failure_visible: true,
      frame_policies: diagnostics.framePolicies,
      query_frames: diagnostics.queryFrames,
      screenshots: [
        '08-collapsed-mobile-390x844.png',
        '09-expanded-mobile-390x844.png',
        '09b-gauges-mobile-390x844.png',
        '10-shared-scrub-bottom-mobile-390x844.png',
        '10-touch-focus-mobile-390x844.png',
        '10b-focus-reopened-mobile-390x844.png',
        '11-failure-visible-mobile-390x844.png',
      ],
    }
  } finally {
    await context.close()
  }
}

function observe(page) {
  const diagnostics = {
    consoleProblems: [],
    pageErrors: [],
    framePolicies: [],
    queryFrames: [],
    queryStatuses: [],
  }
  page.on('console', (message) => {
    if (message.type() === 'warning' || message.type() === 'error') {
      diagnostics.consoleProblems.push({ type: message.type(), text: message.text() })
    }
  })
  page.on('pageerror', (error) => diagnostics.pageErrors.push(error.message))
  page.on('response', (response) => {
    const url = response.url()
    if (
      response.status() === 200 &&
      url.includes('rack.localhost') &&
      url.includes('rack_module=')
    ) {
      diagnostics.framePolicies.push({
        url,
        csp: response.headers()['content-security-policy'] ?? null,
      })
    }
    if (url.includes('/v1/rack/query')) {
      diagnostics.queryFrames.push(response.request().frame() === page.mainFrame() ? 'main' : 'rack-frame')
      diagnostics.queryStatuses.push(response.status())
    }
  })
  return diagnostics
}

async function installBridgeTrace(page) {
  await page.addInitScript(() => {
    globalThis.__m2cSelectionTrace = []
    const originalPostMessage = MessagePort.prototype.postMessage
    MessagePort.prototype.postMessage = function postMessage(message, ...rest) {
      if (
        typeof message === 'object' &&
        message !== null &&
        message.type === 'selection' &&
        typeof message.selection === 'object' &&
        message.selection !== null
      ) {
        globalThis.__m2cSelectionTrace.push(structuredClone(message.selection))
      }
      return originalPostMessage.call(this, message, ...rest)
    }
  })
}

async function waitForVitals(page, collapsed) {
  await page.locator('iframe[data-testid^="rack-plugin-frame-"]').nth(4).waitFor()
  await page.getByText('M2C REGRESSION FIXTURE', { exact: true }).waitFor()
  await frame(page, 'chat').getByTestId('composer').waitFor()
  await frame(page, 'vitals').locator(collapsed ? '.vitals-strip--collapsed' : '.vitals-strip--expanded').waitFor()
  if (!collapsed) {
    await frame(page, 'vitals').getByText('Created', { exact: true }).waitFor()
  }
}

async function gaugeEvidence(vitals) {
  const expected = [
    ['Created', '3/hr'],
    ['Reinforced', 'Not recorded yet'],
    ['Superseded', 'Not recorded yet'],
    ['Merged', 'Not recorded yet'],
    ['Quarantined', 'Not recorded yet'],
    ['Tombstoned', 'Not recorded yet'],
    ['Add-backs', 'Not recorded yet'],
    ['Active units', '12'],
    ['Pinned units', '2'],
    ['Candidates pending', 'Not recorded yet'],
    ['Edges', 'Not recorded yet'],
    ['Staged units', 'Not recorded yet'],
    ['Queue depth', 'Not active yet'],
  ]
  const rendered = {}
  for (const [label, value] of expected) {
    const gauge = vitals.locator('.vitals-gauge').filter({ hasText: label })
    if (await gauge.count() !== 1) {
      throw new Error(`expected one ${label} gauge`)
    }
    await gauge.scrollIntoViewIfNeeded()
    await gauge.locator('span').getByText(label, { exact: true }).waitFor()
    await gauge.locator('strong').getByText(value, { exact: true }).waitFor()
    rendered[label] = value
  }
  return rendered
}

async function resetGaugeScroll(vitals) {
  await vitals.locator('.vitals-gauges').evaluate((element) => {
    element.scrollLeft = 0
  })
}

async function selectionBusEvidence(vitals, expectedId, expectedAsOf) {
  const selections = await vitals.locator('body').evaluate(
    () => globalThis.__m2cSelectionTrace ?? [],
  )
  const matching = selections.filter((selection) =>
    selection.kind === 'spend_lane' &&
    selection.id === expectedId &&
    selection.as_of === expectedAsOf,
  )
  if (matching.length === 0) {
    throw new Error(
      `selection bus did not carry ${expectedId} at ${expectedAsOf}: ${JSON.stringify(selections)}`,
    )
  }
  return matching.at(-1)
}

async function requireAriaExpanded(control, expected, step) {
  const value = await control.getAttribute('aria-expanded')
  if (value !== String(expected)) {
    throw new Error(`${step} exposed aria-expanded=${value}, expected ${expected}`)
  }
  return value
}

async function requireTextFullyVisible(locator, label) {
  await locator.waitFor()
  const result = await locator.evaluate((element) => {
    const range = document.createRange()
    range.selectNodeContents(element)
    const text = range.getBoundingClientRect()
    const strip = element.closest('.vitals-strip')?.getBoundingClientRect()
      ?? document.documentElement.getBoundingClientRect()
    const style = getComputedStyle(element)
    return {
      display: style.display,
      visibility: style.visibility,
      opacity: Number.parseFloat(style.opacity),
      text: { left: text.left, right: text.right, top: text.top, bottom: text.bottom },
      strip: { left: strip.left, right: strip.right, top: strip.top, bottom: strip.bottom },
    }
  })
  if (
    result.display === 'none' ||
    result.visibility === 'hidden' ||
    result.opacity <= 0 ||
    result.text.left < result.strip.left - 1 ||
    result.text.right > result.strip.right + 1 ||
    result.text.top < result.strip.top - 1 ||
    result.text.bottom > result.strip.bottom + 1
  ) {
    throw new Error(`${label} was clipped or hidden: ${JSON.stringify(result)}`)
  }
  return result
}

async function geometry(page) {
  return page.evaluate(() => ({
    viewport: { width: innerWidth, height: innerHeight },
    document: {
      client_width: document.documentElement.clientWidth,
      scroll_width: document.documentElement.scrollWidth,
    },
    modules: [...document.querySelectorAll('[data-rack-module]')].map((element) => ({
      id: element.getAttribute('data-rack-module'),
      grid_height: Number(element.getAttribute('data-grid-height')),
      rect: {
        x: Math.round(element.getBoundingClientRect().x),
        y: Math.round(element.getBoundingClientRect().y),
        width: Math.round(element.getBoundingClientRect().width),
        height: Math.round(element.getBoundingClientRect().height),
      },
    })),
  }))
}

async function frameBoundary(page) {
  return page.locator('iframe[data-testid^="rack-plugin-frame-"]').evaluateAll((frames) =>
    frames.map((element) => ({
      id: element.getAttribute('data-testid'),
      sandbox: element.getAttribute('sandbox'),
      origin: new URL(element.src).origin,
    })),
  )
}

function assertFrameBoundary(frames, policies, expectedCount) {
  if (frames.length !== expectedCount) {
    throw new Error(`expected ${expectedCount} isolated rack frames, received ${frames.length}`)
  }
  for (const record of frames) {
    if (record.sandbox !== 'allow-scripts allow-same-origin' || !record.origin.startsWith('http://rack.localhost:')) {
      throw new Error(`invalid rack frame boundary: ${JSON.stringify(record)}`)
    }
  }
  if (policies.length < expectedCount || policies.some((record) => !record.csp?.includes("connect-src 'none'"))) {
    throw new Error(`rack frame CSP was incomplete: ${JSON.stringify(policies)}`)
  }
}

function assertViewport(result, expected) {
  if (JSON.stringify(result.viewport) !== JSON.stringify(expected)) {
    throw new Error(`wrong viewport: ${JSON.stringify(result.viewport)}`)
  }
  if (result.document.client_width !== expected.width || result.document.scroll_width !== expected.width) {
    throw new Error(`document overflowed: ${JSON.stringify(result.document)}`)
  }
}

function assertRows(result, expected) {
  const panels = result.modules.filter((record) => ['threads', 'chat', 'memory'].includes(record.id))
  const vitals = result.modules.find((record) => record.id === 'vitals')
  if (vitals?.grid_height !== expected.vitals || panels.some((record) => record.grid_height !== expected.panels)) {
    throw new Error(`rack rows were not reallocated: ${JSON.stringify(result.modules)}`)
  }
  assertRenderedStack(result)
}

function assertRenderedStack(result) {
  const vitals = moduleRecord(result, 'vitals')
  const panels = result.modules.filter((record) =>
    ['threads', 'chat', 'memory'].includes(record.id) &&
    record.rect.width > 0 &&
    record.rect.height > 0,
  )
  const expectedVisiblePanels = result.viewport.width > 768 ? 3 : 1
  if (
    panels.length !== expectedVisiblePanels ||
    vitals.rect.width <= 0 ||
    vitals.rect.height <= 0
  ) {
    throw new Error(`rack panels or Vitals did not render: ${JSON.stringify({ panels, vitals })}`)
  }
  if (panels.some((panel) => panel.rect.y + panel.rect.height > vitals.rect.y + 1)) {
    throw new Error(`Vitals overlapped a panel instead of reallocating it: ${JSON.stringify({ panels, vitals })}`)
  }
  if (Math.max(...panels.map((panel) => panel.rect.height)) - Math.min(...panels.map((panel) => panel.rect.height)) > 1) {
    throw new Error(`visible rack panels received different rendered rows: ${JSON.stringify(panels)}`)
  }
  if (vitals.rect.y + vitals.rect.height > result.viewport.height + 1) {
    throw new Error(`Vitals left the rendered viewport: ${JSON.stringify(vitals)}`)
  }
}

function assertReallocation(before, after, direction) {
  const panelIds = ['threads', 'chat', 'memory']
  const panelDeltas = panelIds.flatMap((id) => {
    const beforePanel = moduleRecord(before, id).rect
    const afterPanel = moduleRecord(after, id).rect
    return beforePanel.width > 0 && afterPanel.width > 0
      ? [{ id, delta: afterPanel.height - beforePanel.height }]
      : []
  })
  const beforeVitals = moduleRecord(before, 'vitals').rect
  const afterVitals = moduleRecord(after, 'vitals').rect
  const vitalsDelta = afterVitals.height - beforeVitals.height
  const meaningfulDelta = before.viewport.height * 0.1
  if (
    panelDeltas.length === 0 ||
    (direction === 'collapse' && (
      panelDeltas.some(({ delta }) => delta < meaningfulDelta) ||
      vitalsDelta > -meaningfulDelta ||
      afterVitals.y <= beforeVitals.y
    )) ||
    (direction === 'expand' && (
      panelDeltas.some(({ delta }) => delta > -meaningfulDelta) ||
      vitalsDelta < meaningfulDelta ||
      afterVitals.y >= beforeVitals.y
    ))
  ) {
    throw new Error(`rendered ${direction} did not reallocate space: ${JSON.stringify({ panelDeltas, beforeVitals, afterVitals })}`)
  }
}

async function sharedTimelineEvidence(vitals) {
  const lanes = vitals.locator('.vitals-lane')
  const cursorPositions = []
  const readoutMinutes = []
  const renderedCursors = []
  for (let index = 0; index < await lanes.count(); index += 1) {
    const lane = lanes.nth(index)
    await lane.scrollIntoViewIfNeeded()
    const slider = lane.getByRole('slider')
    const readout = lane.locator('.vitals-lane__readout')
    if (!(await slider.isVisible()) || !(await readout.isVisible())) {
      throw new Error(`lane ${index} scrubber or readout was not visibly rendered`)
    }
    const cursors = lane.locator('.vitals-chart__cursor')
    if (await cursors.count() !== 1) {
      throw new Error(`lane ${index} did not render exactly one shared cursor`)
    }
    const cursorAppearance = await cursors.evaluate((cursor) => {
      const style = getComputedStyle(cursor)
      const rect = cursor.getBoundingClientRect()
      return {
        display: style.display,
        visibility: style.visibility,
        opacity: Number.parseFloat(style.opacity),
        stroke: style.stroke,
        height: rect.height,
      }
    })
    if (
      cursorAppearance.display === 'none' ||
      cursorAppearance.visibility === 'hidden' ||
      cursorAppearance.opacity <= 0 ||
      cursorAppearance.stroke === 'none' ||
      cursorAppearance.height <= 0
    ) {
      throw new Error(`lane ${index} cursor was not visibly rendered: ${JSON.stringify(cursorAppearance)}`)
    }
    renderedCursors.push(cursorAppearance)
    const position = Number(await cursors.getAttribute('x1'))
    if (!Number.isFinite(position) || Math.abs(position - (59 / 60) * 100) > 0.05) {
      throw new Error(`lane ${index} rendered the wrong shared cursor position: ${position}`)
    }
    cursorPositions.push(position)
    const copy = await lane.locator('.vitals-lane__readout > span').innerText()
    readoutMinutes.push(copy.split('·')[0].trim())
  }
  if (
    cursorPositions.length !== 9 ||
    readoutMinutes.length !== 9 ||
    new Set(readoutMinutes).size !== 1
  ) {
    throw new Error(`spend lanes did not share one scrub minute: ${JSON.stringify({ cursorPositions, readoutMinutes })}`)
  }
  return {
    cursor_positions: cursorPositions,
    rendered_minutes: readoutMinutes,
    rendered_cursors: renderedCursors,
  }
}

async function renderedFocusEvidence(page, vitals) {
  await page.waitForTimeout(180)
  const styles = await vitals.locator('.vitals-lane').evaluateAll((rows) =>
    rows.map((row) => {
      const identity = row.querySelector('.vitals-lane__identity')
      const scrubber = row.querySelector('.vitals-lane__scrubber')
      return {
        selected: row.classList.contains('vitals-lane--selected'),
        row_opacity: Number.parseFloat(getComputedStyle(row).opacity),
        text_opacity: identity === null
          ? Number.NaN
          : Number.parseFloat(getComputedStyle(identity).opacity),
        chart_opacity: scrubber === null
          ? Number.NaN
          : Number.parseFloat(getComputedStyle(scrubber).opacity),
        background: getComputedStyle(row).backgroundImage,
      }
    }),
  )
  const selected = styles.filter((style) => style.selected)
  const siblings = styles.filter((style) => !style.selected)
  if (
    selected.length !== 1 ||
    selected[0].row_opacity < 0.99 ||
    selected[0].text_opacity < 0.99 ||
    selected[0].chart_opacity < 0.99 ||
    selected[0].background === 'none' ||
    siblings.some((style) =>
      style.row_opacity < 0.99 ||
      style.text_opacity < 0.7 ||
      style.text_opacity > 0.74 ||
      style.chart_opacity < 0.36 ||
      style.chart_opacity > 0.4
    )
  ) {
    throw new Error(`lane focus was not visibly encoded: ${JSON.stringify(styles)}`)
  }
  return styles
}

function moduleRecord(result, id) {
  const record = result.modules.find((candidate) => candidate.id === id)
  if (record === undefined) {
    throw new Error(`missing rendered rack module ${id}`)
  }
  return record
}

function assertDiagnostics(diagnostics) {
  const expectedFailureWasRendered = diagnostics.queryStatuses.includes(503)
  const unexpectedConsoleProblems = diagnostics.consoleProblems.filter((problem) =>
    !(
      expectedFailureWasRendered &&
      problem.type === 'error' &&
      /Failed to load resource.*503|503.*Service Unavailable/i.test(problem.text)
    ),
  )
  if (unexpectedConsoleProblems.length !== 0 || diagnostics.pageErrors.length !== 0) {
    throw new Error(`browser diagnostics were not clean: ${JSON.stringify(diagnostics)}`)
  }
}

async function scrubAt(page, lane, fraction) {
  const box = await lane.locator('svg').boundingBox()
  if (box === null) {
    throw new Error('spend lane did not have rendered bounds')
  }
  const offset = Math.max(0.5, Math.min(box.width - 0.5, box.width * fraction))
  await page.mouse.move(box.x + offset, box.y + box.height / 2)
}

function frame(page, moduleId) {
  return page.frameLocator(`[data-testid="rack-plugin-frame-${moduleId}"]`)
}

async function capture(page, filename) {
  await page.screenshot({ path: join(evidenceDir, filename) })
}

async function captureLocator(locator, filename) {
  await locator.screenshot({ path: join(evidenceDir, filename) })
}

function startFixture(fixturePort, home) {
  const child = spawn(
    python,
    [
      '-m',
      'uvicorn',
      'verification.m2c.scenario_app:create_scenario_app',
      '--factory',
      '--host',
      '127.0.0.1',
      '--port',
      String(fixturePort),
    ],
    {
      cwd: harnessDir,
      env: {
        ...process.env,
        PYTHONPATH: join(harnessDir, 'src'),
        NOCTURNE_HOME: home,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  )
  child.output = ''
  child.startError = null
  child.on('error', (error) => {
    child.startError = error
  })
  for (const stream of [child.stdout, child.stderr]) {
    stream.setEncoding('utf8')
    stream.on('data', (chunk) => {
      child.output = `${child.output}${chunk}`.slice(-12_000)
    })
  }
  return child
}

async function waitForFixture(child, url) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (child.startError !== null) {
      throw new Error(`M2C fixture could not start: ${child.startError.message}`)
    }
    if (child.exitCode !== null) {
      throw new Error(`M2C fixture exited before startup (${child.exitCode}):\n${child.output}`)
    }
    try {
      const response = await fetch(url)
      if (response.ok) {
        return
      }
    } catch {
      // Startup is still in progress.
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100))
  }
  throw new Error(`M2C fixture did not start:\n${child.output}`)
}

async function stopFixture(child) {
  if (child.pid === undefined) {
    return
  }
  if (child.exitCode !== null) {
    return
  }
  child.kill('SIGTERM')
  const completed = once(child, 'exit')
  const timeout = new Promise((resolveTimeout) => setTimeout(resolveTimeout, 5_000, 'timeout'))
  if (await Promise.race([completed, timeout]) === 'timeout') {
    child.kill('SIGKILL')
    await once(child, 'exit')
  }
}

async function reservePort() {
  const server = createServer()
  server.unref()
  await new Promise((resolveListen, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolveListen)
  })
  const address = server.address()
  if (address === null || typeof address === 'string') {
    throw new Error('could not allocate the M2C fixture port')
  }
  await new Promise((resolveClose, reject) => server.close((error) => error ? reject(error) : resolveClose()))
  return address.port
}

async function fetchJson(url, init) {
  const response = await fetch(url, init)
  const payload = await response.json()
  if (!response.ok) {
    throw new Error(`${response.status} from ${url}: ${JSON.stringify(payload)}`)
  }
  return payload
}
