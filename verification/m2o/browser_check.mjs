/** M2O rendered proof with an owned fixture process and removable browser profile. */

import { spawn } from 'node:child_process'
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
const profile = await mkdtemp(join(tmpdir(), 'nocturne-m2o-profile-'))
const port = await reservePort()
const baseUrl = `http://127.0.0.1:${port}`
const fixture = spawn(
  python,
  [
    '-m',
    'verification.run_fixture',
    'verification.m2o.scenario_app:create_scenario_app',
    '--port',
    String(port),
  ],
  {
    cwd: harnessDir,
    env: { ...process.env, PYTHONPATH: 'src:.' },
    stdio: ['ignore', 'pipe', 'pipe'],
  },
)
let fixtureOutput = ''
fixture.stdout.on('data', (chunk) => { fixtureOutput += chunk })
fixture.stderr.on('data', (chunk) => { fixtureOutput += chunk })
let context

try {
  await waitForFixture(`${baseUrl}/__scenario__/identity`)
  context = await chromium.launchPersistentContext(profile, {
    channel: 'chrome',
    headless: true,
    viewport: { width: 1440, height: 900 },
  })
  await context.addInitScript(seedCatalog)
  const queryAloneRejected = await proveQueryAloneDoesNotMark(context)
  const page = context.pages()[0] ?? await context.newPage()
  const consoleProblems = []
  page.on('console', (message) => {
    if (['warning', 'error'].includes(message.type())) consoleProblems.push(message.text())
  })
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await page.getByText('M2O REGRESSION FIXTURE', { exact: true }).first().waitFor()
  const desktopOverlay = await assertOverlay(page, { width: 1440, height: 900 })

  const vitals = page.frameLocator('iframe[src*="rack_module=vitals"]')
  await vitals.getByText('Receipt drift · 2 lines pending', { exact: true }).waitFor()
  const threads = page.frameLocator('iframe[src*="rack_module=threads"]')
  const cleanup = threads.getByRole('button', { name: 'Remove 2 fixture threads' })
  await cleanup.waitFor()
  await page.screenshot({ path: join(evidenceDir, '01-isolated-pending-desktop.png') })
  await cleanup.click()
  await cleanup.waitFor({ state: 'detached' })
  await threads.getByText('Owner planning notes', { exact: true }).waitFor()
  if (await threads.getByText('Open the H6 verification thread context.', { exact: true }).count()) {
    throw new Error('legacy H6 fixture title survived explicit cleanup')
  }
  await page.screenshot({ path: join(evidenceDir, '02-clean-catalog-desktop.png') })

  await page.setViewportSize({ width: 390, height: 844 })
  const mobileOverlay = await assertOverlay(page, { width: 390, height: 844 })
  await page.screenshot({ path: join(evidenceDir, '03-isolated-mobile.png') })
  const unexpectedDiagnostics = consoleProblems.filter(
    (message) => message !== 'Failed to load resource: the server responded with a status of 503 (Service Unavailable)',
  )
  if (unexpectedDiagnostics.length > 0) {
    throw new Error(`browser diagnostics: ${unexpectedDiagnostics.join(' | ')}`)
  }

  const evidence = {
    fixture: 'M2O REGRESSION',
    base_url: baseUrl,
    profile_removed_on_exit: true,
    query_alone_rejected: queryAloneRejected,
    desktop_overlay: desktopOverlay,
    mobile_overlay: mobileOverlay,
    pending_receipts_visible: 2,
    expected_fixture_chat_503s: consoleProblems.length,
    cleanup: { exact_fixture_entries_removed: 2, ordinary_entry_preserved: true },
    screenshots: [
      '01-isolated-pending-desktop.png',
      '02-clean-catalog-desktop.png',
      '03-isolated-mobile.png',
    ],
  }
  await writeFile(join(evidenceDir, 'rendered.json'), `${JSON.stringify(evidence, null, 2)}\n`)
  console.log(`M2O rendered PASS: ${join(evidenceDir, 'rendered.json')}`)
} finally {
  await context?.close()
  fixture.kill('SIGTERM')
  await Promise.race([
    new Promise((resolveExit) => fixture.once('exit', resolveExit)),
    new Promise((resolveTimeout) => setTimeout(resolveTimeout, 3000)),
  ])
  if (fixture.exitCode === null) fixture.kill('SIGKILL')
  await rm(profile, { recursive: true, force: true })
}

function seedCatalog() {
  const at = '2026-08-03T20:00:00.000Z'
  const catalog = [
    ['00000000-0000-4000-8000-000000000001', 'Open the H6 verification thread context.'],
    ['00000000-0000-4000-8000-000000000002', 'Map the release boundary and hold the queue open.'],
    ['00000000-0000-4000-8000-000000000003', 'Owner planning notes'],
  ].map(([thread_id, title]) => ({ thread_id, title, created_at: at, updated_at: at }))
  localStorage.setItem(
    'harness.thread-catalog.v1',
    JSON.stringify({ state: { catalog, selectedThreadId: catalog[0].thread_id }, version: 0 }),
  )
}

async function proveQueryAloneDoesNotMark(browserContext) {
  const page = await browserContext.newPage()
  try {
    await page.route('**/__scenario__/identity', (route) => route.fulfill({ status: 404 }))
    await page.goto(`${baseUrl}/?fixture=M2O%20REGRESSION`, { waitUntil: 'domcontentloaded' })
    await page.getByTestId('rack-shell').waitFor()
    if (await page.locator('.m2c-regression-fixture').count()) {
      throw new Error('query string alone created a fixture overlay')
    }
    return true
  } finally {
    await page.close()
  }
}

async function assertOverlay(page, viewport) {
  const overlay = page.locator('.m2c-regression-fixture:not(.m2c-regression-fixture--remote)').first()
  await overlay.waitFor()
  const box = await overlay.boundingBox()
  if (box === null || Math.abs(box.x) > 1 || Math.abs(box.y) > 1 ||
      Math.abs(box.width - viewport.width) > 1 || Math.abs(box.height - viewport.height) > 1) {
    throw new Error(`fixture overlay does not cover viewport: ${JSON.stringify({ box, viewport })}`)
  }
  return box
}

async function waitForFixture(url) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (fixture.exitCode !== null) throw new Error(`fixture exited early:\n${fixtureOutput}`)
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // Startup is still in progress.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100))
  }
  throw new Error(`fixture did not start:\n${fixtureOutput}`)
}

async function reservePort() {
  const server = createServer()
  await new Promise((resolveListen, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolveListen)
  })
  const address = server.address()
  if (typeof address !== 'object' || address === null) throw new Error('port reservation failed')
  await new Promise((resolveClose, reject) => server.close((error) => error ? reject(error) : resolveClose()))
  return address.port
}
