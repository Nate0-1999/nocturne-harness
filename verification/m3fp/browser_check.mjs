/** SPEC D.2 148: the packaged Rack heartbeat reaches gate, answer, receipt, and journal. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const baseUrl = argument('--base-url')
const fixture = argument('--fixture')
const evidenceDir = resolve(argument('--evidence-dir'))
const prompt = 'Open the memory gate, then answer the heartbeat check.'
const answer = 'M2H final post: the relay stays explicit, candidates remain reviewable, and contradictions never passively resolve.'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 720 } })
const page = await context.newPage()

try {
  await mkdir(evidenceDir, { recursive: true })
  const response = await page.goto(`${baseUrl}/?fixture=${encodeURIComponent(fixture)}`, {
    waitUntil: 'domcontentloaded',
  })
  if (response === null || !response.ok()) {
    throw new Error(`packaged heartbeat did not load: ${response?.status() ?? 'no response'}`)
  }

  const threads = frame('threads')
  const conversation = frame('conversation')
  await threads.getByTestId('new-thread').waitFor({ state: 'visible' })
  await threads.locator('.thread-item--selected').waitFor({ state: 'visible' })
  await conversation.getByTestId('composer').waitFor({ state: 'visible' })
  await waitUntil(async () => conversation.getByTestId('composer').isEnabled())

  await conversation.getByTestId('composer').fill(prompt)
  await conversation.getByTestId('composer').press('Enter')
  await frame('gate').getByTestId('memory-gate').waitFor({ state: 'visible' })
  await page.screenshot({ path: resolve(evidenceDir, '01-first-prompt-gate.png') })

  await frame('gate').getByTestId('memory-gate-continue').click()
  await conversation.getByText(answer, { exact: true }).waitFor({ state: 'visible' })
  await page.screenshot({ path: resolve(evidenceDir, '02-first-answer.png') })

  let trace
  await waitUntil(async () => {
    trace = await fetchJson(`${baseUrl}/__scenario__/heartbeat`)
    return trace.receipt_lines > 0 && journalContains(trace, prompt, answer)
  })
  if (
    trace.packaged_assets !== true ||
    trace.prepare_calls !== 1 ||
    trace.commit_calls !== 1 ||
    trace.receipt_lines < 1
  ) {
    throw new Error(`heartbeat boundaries are not exact: ${JSON.stringify(trace)}`)
  }

  const result = {
    fixture,
    packaged_assets: trace.packaged_assets,
    first_prompt_prepare_calls: trace.prepare_calls,
    first_prompt_commit_calls: trace.commit_calls,
    receipt_lines: trace.receipt_lines,
    journal_has_prompt_and_answer: true,
  }
  const toolPrompt = 'Explain, run one bash command, then explain the result.'
  const toolAnswer = 'I will check the shell.\n\nThe shell returned M3FZ-HEARTBEAT.\n\n'
  await page.reload({ waitUntil: 'domcontentloaded' })
  await conversation.getByText(answer, { exact: true }).waitFor({ state: 'visible' })
  await conversation.getByTestId('composer').fill(toolPrompt)
  await conversation.getByTestId('composer').press('Enter')
  await conversation.getByText('The shell returned M3FZ-HEARTBEAT.', { exact: true })
    .waitFor({ state: 'visible' })
  await waitUntil(async () => {
    trace = await fetchJson(`${baseUrl}/__scenario__/heartbeat`)
    return trace.conversations.some(({ messages }) => {
      const user = messages.findLast((message) => message.content === toolPrompt)
      const assistant = messages.findLast((message) => message.run_id === user?.run_id &&
        message.role === 'assistant')
      return user?.state === 'end_turn' && assistant?.partial === false &&
        assistant.content === toolAnswer &&
        assistant.events.some((event) => event.event_kind === 'proposed_response' &&
          event.primary === 'Check it again.') &&
        assistant.events.some((event) => event.event_kind === 'function_tool_result' &&
          JSON.stringify(event).includes('M3FZ-HEARTBEAT'))
    })
  })
  await page.screenshot({ path: resolve(evidenceDir, '03-talk-tool-talk.png') })
  result.tool_turn_ends_clean_with_proposal_and_journal = true
  await page.reload({ waitUntil: 'domcontentloaded' })
  await conversation.getByTestId('composer').fill('Show the heartbeat failure reason.')
  await conversation.getByTestId('composer').press('Enter')
  const failure = 'Run error · The heartbeat model stopped unexpectedly. · partial kept'
  await conversation.getByText(failure, { exact: true }).waitFor({ state: 'visible' })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await conversation.getByText(failure, { exact: true }).waitFor({ state: 'visible' })
  await page.screenshot({ path: resolve(evidenceDir, '04-failure-reason-after-reload.png') })
  result.failure_reason_survives_reload = true
  await writeFile(
    resolve(evidenceDir, 'heartbeat.json'),
    `${JSON.stringify(result, null, 2)}\n`,
    'utf8',
  )
  console.log(`M3FP packaged heartbeat PASS: ${JSON.stringify(result)}`)
} finally {
  await context.close()
  await browser.close()
}

function frame(moduleId) {
  return page.frameLocator(`[data-testid="rack-plugin-frame-${moduleId}"]`)
}

function journalContains(trace, expectedPrompt, expectedAnswer) {
  return trace.conversations.some(({ messages }) => {
    const contents = messages.map((message) => message.content)
    return contents.includes(expectedPrompt) && contents.includes(expectedAnswer)
  })
}

async function waitUntil(predicate, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  while (Date.now() < deadline) {
    try {
      if (await predicate()) return
    } catch (error) {
      lastError = error
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100))
  }
  throw lastError ?? new Error('heartbeat condition did not settle')
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
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`${name} is required`)
  }
  return value
}
