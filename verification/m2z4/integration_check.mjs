/** One connected M2Z4 proof through real Spine, Harness, and the built Console. */

import { execFileSync, spawn } from 'node:child_process'
import { access, mkdtemp, rm, writeFile } from 'node:fs/promises'
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
const profile = await mkdtemp(join(tmpdir(), 'nocturne-m2z4-integration-'))
const port = await reservePort()
const baseUrl = `http://127.0.0.1:${port}`
const dockerHost = process.env.DOCKER_HOST ?? currentDockerHost()
const tracePath = join(evidenceDir, 'connected-trace.json')
const screenshotPath = join(evidenceDir, '08-connected-worker-proposal-audition.png')
const threadId = '00000000-0000-4000-8000-000000000404'

await access(join(harnessDir, 'web/dist/index.html'))

const fixture = spawn(
  python,
  [
    '-m',
    'verification.run_fixture',
    'verification.m2z4.integration_app:create_integration_app',
    '--port',
    String(port),
  ],
  {
    cwd: harnessDir,
    env: {
      ...process.env,
      PYTHONPATH: 'src:.:../spine/src',
      PYTHONUNBUFFERED: '1',
      DOCKER_HOST: dockerHost,
      TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE: '/var/run/docker.sock',
      TESTCONTAINERS_RYUK_DISABLED: 'true',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  },
)
let fixtureOutput = ''
fixture.stdout.on('data', (chunk) => { fixtureOutput += chunk })
fixture.stderr.on('data', (chunk) => { fixtureOutput += chunk })
let context

try {
  await waitForFixture(`${baseUrl}/__scenario__/identity`)
  const startupTrace = await waitForTrace(
    (trace) => trace.worker.completions.some((completion) => completion.status === 'not_due'),
    15_000,
    'the real worker startup due-check to complete',
  )
  assert(startupTrace.database.active_versions.join(',') === 'v0', 'v0 was not initially active')

  context = await chromium.launchPersistentContext(profile, {
    channel: 'chrome',
    headless: true,
    viewport: { width: 1440, height: 900 },
  })
  await context.addInitScript(seedSelectedThread, { threadId })
  const page = context.pages()[0] ?? await context.newPage()
  const network = { consoleQueries: [], auditions: [], activations: [] }
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname === '/v1/rack/query' && url.searchParams.get('resource') === 'scorer_console') {
      network.consoleQueries.push({ method: request.method(), url: request.url() })
    } else if (url.pathname === '/v1/rack/scorers/audition') {
      network.auditions.push({ method: request.method(), body: request.postDataJSON() })
    } else if (/^\/v1\/rack\/scorers\/[^/]+\/activate$/.test(url.pathname)) {
      network.activations.push({ method: request.method(), body: request.postDataJSON() })
    }
  })

  await page.goto(`${baseUrl}/?fixture=M2Z4%20REGRESSION`, { waitUntil: 'domcontentloaded' })
  await page.getByText('M2Z4 REGRESSION FIXTURE', { exact: true }).first().waitFor()
  const header = page.frameLocator('iframe[title="Nocturne Header"]')
  await header.getByRole('button', { name: 'Injection', exact: true }).click()
  const consoleFrame = page.frameLocator('iframe[title="Injection Console"]')
  await consoleFrame.getByRole('heading', { name: 'Injection Console', exact: true }).waitFor()
  const current = consoleFrame.getByRole('button', { name: 'Current', exact: true })
  await current.click()
  await waitForLocatorAttribute(current, 'aria-pressed', 'true')
  await consoleFrame.locator('.console-active', { hasText: 'Current recipe v0' }).waitFor()
  if (await consoleFrame.locator('.proposal-card').count() !== 0) {
    throw new Error('a proposal existed before the test-only graded work was inserted')
  }

  const work = await fetchJson(`${baseUrl}/__scenario__/graded-work`, { method: 'POST' })
  assert(work.test_only === true, 'graded-work driver did not identify itself as test-only')
  assert(work.inserted_events === 5, 'graded-work driver inserted an unexpected event count')

  const workerTrace = await waitForTrace(
    (trace) => trace.database.learner_runs.some(
      (run) => run.trigger === 'background' && run.result === 'proposed',
    ),
    30_000,
    'the notified real worker to persist its winning background receipt',
  )
  const run = workerTrace.database.learner_runs.find(
    (candidate) => candidate.trigger === 'background' && candidate.result === 'proposed',
  )
  assert(typeof run?.proposal_version === 'string', 'background receipt has no proposal version')
  const proposalVersion = run.proposal_version

  const proposal = consoleFrame.locator('.proposal-card', { hasText: proposalVersion })
  await proposal.waitFor({ timeout: 12_000 })
  await proposal.getByText('BACKGROUND PROPOSAL', { exact: true }).waitFor()
  const renderedProposal = compact(await proposal.innerText())
  const auditionButton = proposal.getByRole('button', { name: 'Audition', exact: true })
  const activateButton = proposal.getByRole('button', { name: 'Activate', exact: true })
  await waitForEnabled(auditionButton)
  await activateButton.waitFor()
  await auditionButton.click()

  await consoleFrame
    .getByRole('heading', { name: `Auditioning ${proposalVersion}`, exact: true })
    .waitFor()
  const candidate = consoleFrame.locator('.candidate-ledger article', {
    hasText: 'No silent inference',
  })
  await candidate.waitFor()
  const renderedCandidate = compact(await candidate.innerText())
  assert(renderedCandidate.includes('would add'), 'audition did not render would add')
  const renderedActive = compact(await consoleFrame.locator('.console-active').innerText())
  assert(renderedActive.includes('Current recipe v0'), 'audition changed the rendered incumbent')
  await page.screenshot({ path: screenshotPath })

  const finalTrace = await waitForTrace(
    (trace) => trace.harness.auditions.length === 1 &&
      trace.harness.canonical_console?.proposed_versions?.some(
        (candidateVersion) => candidateVersion.version === proposalVersion,
      ),
    10_000,
    'the canonical Console read and real audition callback to be recorded',
  )
  assertConnectedProof(finalTrace, proposalVersion, network)

  const evidence = {
    ...finalTrace,
    browser: {
      built_console: 'current web/dist',
      proposal_version: proposalVersion,
      rendered_proposal: renderedProposal,
      rendered_candidate: renderedCandidate,
      rendered_active: renderedActive,
      audition_heading: `Auditioning ${proposalVersion}`,
      activate_visible_but_not_clicked: await activateButton.isVisible(),
      network,
      screenshot: '08-connected-worker-proposal-audition.png',
    },
  }
  await writeFile(tracePath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8')
  console.log(`M2Z4 connected integration PASS: ${tracePath}`)
} finally {
  await context?.close()
  fixture.kill('SIGTERM')
  await Promise.race([
    new Promise((resolveExit) => fixture.once('exit', resolveExit)),
    new Promise((resolveTimeout) => setTimeout(resolveTimeout, 45_000)),
  ])
  if (fixture.exitCode === null) fixture.kill('SIGKILL')
  await rm(profile, { recursive: true, force: true })
}

function seedSelectedThread({ threadId: selectedThreadId }) {
  const at = '2026-08-09T18:00:00.000Z'
  const catalog = [{
    thread_id: selectedThreadId,
    title: 'Disposable learner proof',
    created_at: at,
    updated_at: at,
    project_key: null,
  }]
  localStorage.setItem(
    'harness.thread-catalog.v1',
    JSON.stringify({ state: { catalog, selectedThreadId }, version: 0 }),
  )
}

function assertConnectedProof(trace, proposalVersion, network) {
  const completions = trace.worker.completions
  assert(trace.worker.wake_requests.length === 1, 'real worker notification count changed')
  assert(completions.some((row) => row.status === 'not_due'), 'startup worker completion missing')
  assert(
    completions.some(
      (row) => row.status === 'proposed' && row.proposal_version === proposalVersion,
    ),
    'notified real worker completion missing',
  )
  const proposal = trace.database.learner_proposals.find((row) => row.version === proposalVersion)
  assert(proposal?.active === false, 'winning proposal did not remain inactive')
  assert(proposal?.learner_status === 'proposed', 'winning proposal lost its learner marker')
  assert(trace.database.active_versions.join(',') === 'v0', 'incumbent v0 was not active')
  assert(trace.database.activation_rows === 0, 'an activation receipt was persisted')
  const canonical = trace.harness.canonical_console
  assert(canonical?.active_version === 'v0', 'canonical Console did not report v0 active')
  assert(canonical?.scope === 'CURRENT', 'canonical Console was not in Current scope')
  assert(canonical?.thread_id === threadId, 'canonical Console used another thread')
  assert(
    canonical?.proposed_versions?.some((row) => row.version === proposalVersion),
    'canonical Console did not carry the worker proposal',
  )
  assert(
    canonical?.learning?.retrain_runs?.some(
      (row) => row.trigger === 'background' &&
        row.result === 'proposed' &&
        row.proposal_version === proposalVersion,
    ),
    'canonical Console learning view did not carry the background receipt',
  )
  assert(
    canonical?.candidates?.some((row) => row.label === 'No silent inference'),
    'canonical Current Console did not carry the audition candidate',
  )
  assert(trace.harness.auditions.length === 1, 'real audition callback count changed')
  const audition = trace.harness.auditions[0]
  assert(audition.request.proposal_version === proposalVersion, 'audition requested another version')
  assert(audition.response.instant.status === 'ready', 'Spine audition was not replayable')
  assert(
    audition.response.instant.candidates.some(
      (row) => row.disposition === 'would_add',
    ),
    'Spine audition did not produce would_add',
  )
  assert(trace.harness.activation_attempts.length === 0, 'Harness activation callback was invoked')
  assert(network.consoleQueries.length >= 2, 'current Console did not poll the canonical route')
  assert(network.auditions.length === 1, 'browser did not make exactly one audition request')
  assert(network.auditions[0].method === 'POST', 'browser audition was not POST')
  assert(network.auditions[0].body.proposal_version === proposalVersion, 'browser audition body drifted')
  assert(
    Object.keys(network.auditions[0].body).sort().join(',') === 'injection_id,proposal_version',
    'browser audition request gained an unexpected authority field',
  )
  assert(network.activations.length === 0, 'browser attempted proposal activation')
}

async function fetchJson(url, init) {
  const response = await fetch(url, init)
  const payload = await response.json()
  if (!response.ok) throw new Error(`${response.status} from ${url}: ${JSON.stringify(payload)}`)
  return payload
}

async function waitForTrace(predicate, timeoutMs, description) {
  const deadline = Date.now() + timeoutMs
  let latest
  while (Date.now() < deadline) {
    latest = await fetchJson(`${baseUrl}/__scenario__/trace`)
    if (predicate(latest)) return latest
    if (fixture.exitCode !== null) throw new Error(`fixture exited early:\n${fixtureOutput}`)
    await new Promise((resolveWait) => setTimeout(resolveWait, 100))
  }
  throw new Error(`timed out waiting for ${description}: ${JSON.stringify(latest)}`)
}

async function waitForFixture(url) {
  for (let attempt = 0; attempt < 240; attempt += 1) {
    if (fixture.exitCode !== null) throw new Error(`fixture exited early:\n${fixtureOutput}`)
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // Container, migration, and ASGI startup are still in progress.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 500))
  }
  throw new Error(`fixture did not start within 120 seconds:\n${fixtureOutput}`)
}

async function waitForEnabled(locator) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (await locator.isEnabled()) return
    await new Promise((resolveWait) => setTimeout(resolveWait, 100))
  }
  throw new Error('Audition did not become enabled for the selected frozen gate')
}

async function waitForLocatorAttribute(locator, name, expected) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (await locator.getAttribute(name) === expected) return
    await new Promise((resolveWait) => setTimeout(resolveWait, 100))
  }
  throw new Error(`${name} did not become ${expected}`)
}

async function reservePort() {
  const server = createServer()
  await new Promise((resolveListen, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolveListen)
  })
  const address = server.address()
  if (typeof address !== 'object' || address === null) throw new Error('port reservation failed')
  await new Promise((resolveClose, reject) => {
    server.close((error) => error ? reject(error) : resolveClose())
  })
  return address.port
}

function compact(value) {
  return value.replace(/\s+/g, ' ').trim()
}

function currentDockerHost() {
  const value = execFileSync(
    'docker',
    ['context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'],
    { encoding: 'utf8' },
  ).trim()
  if (value.length === 0) throw new Error('the current Docker context has no endpoint')
  return value
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}
