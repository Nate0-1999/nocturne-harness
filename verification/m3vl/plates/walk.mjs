/** M3VL send-back 1 walk: real threads, a real Symphony and a real curator pass under a disposable
 * verification identity, driven headless through the real app. Phases run separately:
 *   node walk.mjs --base-url http://127.0.0.1:8765 --project <dir> --evidence-dir <dir> --phase threads|symphony */

import { createRequire } from 'node:module'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'

const requireFromWeb = createRequire(new URL('../../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const baseUrl = argument('--base-url')
const project = argument('--project')
const evidenceDir = resolve(argument('--evidence-dir'))
const phase = argument('--phase')
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
const page = await context.newPage()
const receipt = resolve(evidenceDir, 'receipts', 'walk.json')
const sent = new Map()

const THREADS = [
  ['Read every Markdown file in references one at a time with the read tool, then write notes/summary.md with one sentence per file.',
    'Now read src/riverflow/basin.py and src/riverflow/routing.py, and add a short module docstring to each with the edit tool.'],
  ['Read data/stations.csv and src/riverflow/gauge.py, then write notes/gauges.md explaining how the gauge readings are loaded.',
    'Read tests/test_basin.py and src/riverflow/confluence.py, then add a test for merge() to tests/test_confluence.py.'],
]

try {
  await mkdir(resolve(evidenceDir, 'receipts'), { recursive: true })
  const response = await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  if (response === null || !response.ok()) throw new Error(`app did not load: ${response?.status()}`)
  await frame('threads').getByTestId('new-thread').waitFor({ state: 'visible' })
  await page.getByRole('button', { name: 'Sheet', exact: true }).click()
  const walk = JSON.parse(await readFile(receipt, 'utf8').catch(() => '{"threads":[]}'))
  if (phase === 'threads') {
    // Resumable: each sent prompt is recorded, so a rerun continues where the last one stopped.
    for (const [index, prompts] of THREADS.entries()) {
      walk.threads[index] ??= { thread_id: argument(`--thread-${index}`, false) ?? await createThread(), prompts: [] }
      const thread = walk.threads[index]
      sent.set(thread.thread_id, await runsDone(thread.thread_id))
      await frame('threads').locator(`[data-thread-id="${thread.thread_id}"] button`).first().click()
      for (const prompt of prompts.slice(thread.prompts.length)) {
        await send(prompt)
        await settled(thread.thread_id, 1_200_000)
        thread.prompts.push(prompt)
        await writeFile(receipt, `${JSON.stringify(walk, null, 2)}\n`)
      }
    }
  }
  if (phase === 'symphony') {
    // The owner phrase opens a deliberation card; the person composes and signs it (ADR-012).
    const threadId = walk.symphony?.thread_id ?? argument('--thread', false) ?? await createThread()
    walk.symphony = { thread_id: threadId }
    await frame('threads').locator(`[data-thread-id="${threadId}"] button`).first().click()
    // A prompt is refused until the selected thread's authoritative snapshot arrives: wait for the history,
    // then confirm a new deliberation card appeared.
    const cards = frame('conversation').getByTestId('symphony-deliberation')
    await page.waitForTimeout(4000)
    const before = await cards.count()
    let asked = false
    for (let attempt = 0; attempt < 3 && !asked; attempt++) {
      const mode = frame('conversation').getByLabel('Orchestration mode')
      if (attempt) await mode.selectOption('Duet')
      await mode.selectOption('Symphony')
      asked = await waitUntil(async () => await cards.count() > before, 20_000).then(() => true, () => false)
    }
    if (!asked) throw new Error('the Symphony deliberation was not requested')
    const card = frame('conversation').getByTestId('symphony-deliberation').last()
    await card.waitFor({ state: 'visible', timeout: 120_000 })
    const fill = async (label, value) => card.getByLabel(label, { exact: true }).first().fill(String(value))
    await fill('Desired outcome', 'Add route_flood() to src/riverflow/routing.py that attenuates a flood hydrograph along a reach, with a test in tests/test_routing.py.')
    await fill('Why this deserves a Symphony', 'Two independent attempts at the routing math, judged, beat one guess.')
    await fill('Step 1', 'Implement route_flood() and its test')
    await fill('Done when', 'python -m pytest passes including tests/test_routing.py')
    for (const field of await card.getByLabel('Rubric', { exact: true }).all()) await field.fill('The function is correct, documented and tested.')
    for (const field of await card.getByLabel('Required evidence', { exact: true }).all()) await field.fill('The pytest output and the diff.')
    for (const field of await card.getByLabel('Precalculated metric', { exact: true }).all()) await field.fill('pytest pass count')
    for (const [label, value] of [['Attempts', 2], ['Spend USD', 2], ['Rounds', 1], ['Depth', 0], ['Children / attempt', 0], ['Minutes', 10]]) await fill(label, value)
    const toggle = card.locator('.symphony-sign input[type="checkbox"]')
    if (!(await toggle.isChecked())) await toggle.check()
    await card.getByRole('button', { name: 'Sign & run Symphony' }).click()
    await card.getByText('Signed and launched').waitFor({ timeout: 60_000 })
    walk.symphony = { thread_id: threadId, opened_by: 'Orchestration mode → Symphony', authority: { attempts: 2, spend_wall_usd: 2, max_rounds: 1, depth_cap: 0, children_per_attempt: 0, duration_minutes: 10 }, launched_at: new Date().toISOString() }
    await writeFile(receipt, `${JSON.stringify(walk, null, 2)}\n`)
  }
  if (phase === 'turn') {
    // One more real turn in an existing thread, sent and left running so a recording sees it live.
    const [threadId, prompt] = [argument('--thread'), argument('--prompt')]
    await frame('threads').locator(`[data-thread-id="${threadId}"] button`).first().click()
    // A prompt is refused until the selected thread's authoritative snapshot arrives; wait for its history.
    await frame('conversation').locator('[data-role="assistant"]').first().waitFor({ timeout: 60_000 })
    await page.waitForTimeout(2000)
    await send(prompt)
    const journal = resolve(argument('--home'), 'transcripts', `${createHash('sha256').update(threadId).digest('hex')}.jsonl`)
    await waitUntil(async () => (await readFile(journal, 'utf8')).includes(prompt.slice(0, 40)), 30_000)
    walk.live_turns = [...(walk.live_turns ?? []), { thread_id: threadId, prompt, sent_at: new Date().toISOString() }]
    await writeFile(receipt, `${JSON.stringify(walk, null, 2)}\n`)
  }
  console.log(`M3VL walk phase ${phase} done`)
} finally {
  await context.close()
  await browser.close()
}

async function createThread() {
  const before = (await fetchJson(`${baseUrl}/v1/transcripts/catalog`)).threads.map((thread) => thread.thread_id)
  const threads = frame('threads')
  await threads.getByTestId('new-thread').click()
  await threads.getByTestId('thread-workspace-root').fill(project)
  await threads.getByTestId('thread-create').getByRole('button', { name: 'Create' }).click()
  let created
  await waitUntil(async () => {
    created = (await fetchJson(`${baseUrl}/v1/transcripts/catalog`)).threads.find((thread) => !before.includes(thread.thread_id))
    return created !== undefined
  })
  await waitUntil(async () => frame('conversation').getByTestId('composer').isEnabled())
  return created.thread_id
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

async function runsDone(threadId) {
  // The thread's own journal is authoritative: a turn is settled when its run.done is recorded.
  const journal = resolve(argument('--home'), 'transcripts', `${createHash('sha256').update(threadId).digest('hex')}.jsonl`)
  return (await readFile(journal, 'utf8').catch(() => '')).split('\n')
    .filter((line) => line.includes('"type":"run.done"') || line.includes('"type": "run.done"')).length
}

async function settled(threadId, timeoutMs) {
  const target = sent.get(threadId) + 1
  await waitUntil(async () => await runsDone(threadId) >= target, timeoutMs)
  sent.set(threadId, target)
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
    await new Promise((resolveWait) => setTimeout(resolveWait, 500))
  }
  throw lastError ?? new Error('walk condition did not settle')
}

async function fetchJson(url) {
  const response = await fetch(url)
  const payload = await response.json()
  if (!response.ok) throw new Error(`${response.status} from ${url}: ${JSON.stringify(payload)}`)
  return payload
}

function argument(name, required = true) {
  const index = args.indexOf(name)
  const value = index < 0 ? undefined : args[index + 1]
  if (typeof value !== 'string' || value.length === 0) {
    if (required) throw new Error(`${name} is required`)
    return undefined
  }
  return value
}
