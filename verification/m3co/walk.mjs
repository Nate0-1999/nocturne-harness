/** FL-198: an oversized query is cut to an error with a head; an oversized sub-agent return is
 * sent back a deterministic shorten-by; the Security module shows both. Drives the real app. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const baseUrl = argument('--base-url')
const evidenceDir = resolve(argument('--evidence-dir'))
const queryPrompt = 'Using only the bash tool, run exactly this command: cat uv.lock uv.lock — then tell me in one sentence what the tool returned to you.'
const delegatePrompt = 'Call the delegate_task tool once with share_percent set to 0.1 and this task: "Without using any tools, write about 700 words explaining what a memory palace is and how the method of loci works, as your answer." Then tell me in two sentences what came back and whether it had been shortened.'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
const page = await context.newPage()

try {
  await mkdir(evidenceDir, { recursive: true })
  const response = await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  if (response === null || !response.ok()) throw new Error(`app did not load: ${response?.status()}`)
  const threads = frame('threads')
  const conversation = frame('conversation')
  await threads.getByTestId('new-thread').waitFor({ state: 'visible' })
  await conversation.getByTestId('composer').waitFor({ state: 'visible' })
  await waitUntil(async () => conversation.getByTestId('composer').isEnabled())
  // The Security module lives in the library until a person adds it to the Work layer.
  await page.getByRole('button', { name: 'Library', exact: true }).click()
  await page.locator('li', { hasText: 'Security' }).getByRole('button', { name: 'Add', exact: true }).click()
  await page.getByRole('button', { name: 'Library', exact: true }).click()
  // The Sheet stacks every module unscaled, so each capture is one scroll away.
  await page.getByRole('button', { name: 'Sheet', exact: true }).click()
  const security = frame('security')
  await security.getByTestId('security-shares').waitFor({ state: 'visible' })

  const captureOnly = args.includes('--capture-only')
  const delegateOnly = args.includes('--delegate-only')
  if (!captureOnly && !delegateOnly) {
    await send(queryPrompt)
    await conversation.getByText(/token/).first().waitFor({ state: 'visible', timeout: 180_000 })
  }
  await settled()
  await page.locator('[data-testid="rack-plugin-frame-conversation"]').scrollIntoViewIfNeeded()
  await page.screenshot({ path: resolve(evidenceDir, 'FL-198-query.png') })
  let overwhelm = await fetchJson(`${baseUrl}/v1/rack/query?resource=overwhelm&as_of=now`)
  const queryCut = overwhelm.data.cuts.find((cut) => cut.kind === 'query' && cut.action === 'cut')
  if (!queryCut) throw new Error(`no query cut recorded: ${JSON.stringify(overwhelm.data.cuts)}`)

  if (!captureOnly) await send(delegatePrompt)
  await waitUntil(async () => {
    overwhelm = await fetchJson(`${baseUrl}/v1/rack/query?resource=overwhelm&as_of=now`)
    return overwhelm.data.cuts.some((cut) => cut.kind === 'sub_agent')
  }, 900_000)
  await settled(1_200_000)
  await conversation.getByTestId('worker-return').first().waitFor({ state: 'visible' })
  await page.locator('[data-testid="rack-plugin-frame-conversation"]').scrollIntoViewIfNeeded()
  await page.screenshot({ path: resolve(evidenceDir, 'FL-198-subagent.png') })

  overwhelm = await fetchJson(`${baseUrl}/v1/rack/query?resource=overwhelm&as_of=now`)
  await page.locator('[data-testid="rack-plugin-frame-security"]').scrollIntoViewIfNeeded()
  await waitUntil(async () => (await security.locator('[data-testid="security-cuts"] tbody tr').count()) >= overwhelm.data.cuts.length)
  await page.screenshot({ path: resolve(evidenceDir, 'FL-198.png') })
  const catalog = await fetchJson(`${baseUrl}/v1/transcripts/catalog`)
  await writeFile(resolve(evidenceDir, 'receipts', 'overwhelm.json'), `${JSON.stringify(overwhelm, null, 2)}\n`)
  await writeFile(resolve(evidenceDir, 'receipts', 'walk.json'), `${JSON.stringify({
    base_url: baseUrl,
    identity: catalog.identity,
    threads: catalog.threads.map(({ thread_id, title, workspace_root }) => ({ thread_id, title, workspace_root })),
    prompts: [queryPrompt, delegatePrompt],
    query_cut: queryCut,
    sub_agent_cuts: overwhelm.data.cuts.filter((cut) => cut.kind === 'sub_agent'),
    bounds: overwhelm.data.bounds,
  }, null, 2)}\n`)
  console.log(`M3CO walk PASS: ${overwhelm.data.cuts.length} cuts/send-backs recorded`)
} finally {
  await context.close()
  await browser.close()
}

async function send(prompt) {
  const conversation = frame('conversation')
  await waitUntil(async () =>
    await conversation.getByTestId('composer').isEnabled() &&
    await conversation.getByTestId('composer').inputValue() === '')
  await conversation.getByTestId('composer').fill(prompt)
  await conversation.getByTestId('composer').press('Enter')
  try {
    await frame('gate').getByTestId('memory-gate').waitFor({ state: 'visible', timeout: 20_000 })
    await frame('gate').getByTestId('memory-gate-continue').click()
  } catch {
    // Later turns open no first-turn memory check.
  }
}

async function settled(timeoutMs = 240_000) {
  const conversation = frame('conversation')
  await waitUntil(async () =>
    await conversation.getByTestId('composer').isEnabled() &&
    await conversation.getByTestId('composer').inputValue() === '', timeoutMs)
}

function frame(moduleId) {
  return page.frameLocator(`[data-testid="rack-plugin-frame-${moduleId}"]`)
}

async function waitUntil(predicate, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  while (Date.now() < deadline) {
    try {
      if (await predicate()) return
    } catch (error) {
      lastError = error
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 250))
  }
  throw lastError ?? new Error('walk condition did not settle')
}

async function fetchJson(url) {
  const response = await fetch(url)
  const payload = await response.json()
  if (!response.ok) throw new Error(`${response.status} from ${url}: ${JSON.stringify(payload)}`)
  return payload
}

function argument(name) {
  const index = args.indexOf(name)
  const value = index < 0 ? undefined : args[index + 1]
  if (typeof value !== 'string' || value.length === 0) throw new Error(`${name} is required`)
  return value
}
