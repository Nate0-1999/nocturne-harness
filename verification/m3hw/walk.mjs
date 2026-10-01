/** M3HW walks on the real app, one fresh run per call: FL-198 (an oversized query is cut, an
 * oversized sub-agent return is sent back, the Security module lists both and keeps every cut
 * across restarts), FL-184 (the Jobs module lists every job with its state), FL-133 (the Palace
 * module changes while LIVE as memories arrive and a curator pass runs; beside its plate).
 * usage: node walk.mjs <app-url> <out-dir> <FL-198|FL-184|FL-133> <run> */
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const [base, out, row, run] = process.argv.slice(2)
const tag = `${row}-run${run}`
const stamp = new Date().toISOString().slice(11, 19).replaceAll(':', '')  // job names stay unique across walks
mkdirSync(`${out}/receipts`, { recursive: true })
const context = await chromium.launchPersistentContext(process.env.WALK_PROFILE ?? '/private/tmp/m3hw-work/walk-profile', {
  channel: 'chrome', headless: true, viewport: { width: 1600, height: 1000 },
  args: ['--use-angle=metal', '--enable-unsafe-webgpu'],
})
const page = context.pages()[0] ?? await context.newPage()
const frame = (id) => page.frameLocator(`[data-testid="rack-plugin-frame-${id}"]`)
const json = async (path, init) => {
  const response = await fetch(`${base}${path}`, init)
  if (!response.ok) throw new Error(`${response.status} ${path}: ${await response.text()}`)
  return response.json()
}
async function waitUntil(predicate, timeoutMs = 60_000, label = 'condition') {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try { if (await predicate()) return } catch { /* retry */ }
    await page.waitForTimeout(1000)
  }
  throw new Error(`${label} did not happen within ${timeoutMs / 1000} s`)
}
async function stage(modules) {
  await page.goto(base, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'Library', exact: true }).click()
  for (const name of modules) {
    const add = page.getByRole('button', { name: `Add ${name}`, exact: true })
    if (await add.count() && await add.isEnabled()) await add.click()
  }
  await page.getByRole('button', { name: 'Library', exact: true }).click()
  if (await page.getByRole('button', { name: 'Sheet', exact: true }).getAttribute('aria-pressed') !== 'true')
    await page.getByRole('button', { name: 'Sheet', exact: true }).click()
  await page.waitForTimeout(5000)
}
async function freshThread() {
  const empty = () => frame('conversation').getByText('Send a prompt when you').count()
  for (let attempt = 0; attempt < 3 && !(await empty()); attempt += 1) {
    await frame('threads').getByTestId('new-thread').click({ force: true, timeout: 15000 })
    // An empty current thread is already fresh; otherwise the folder form asks to Create.
    await frame('threads').getByRole('button', { name: /^create$/i }).click({ force: true, timeout: 10000 }).catch(() => {})
    await page.waitForTimeout(3000)
  }
  if (!(await empty())) throw new Error('no fresh empty thread opened')
}
async function send(prompt) {
  const composer = frame('conversation').getByTestId('composer')
  await composer.fill(prompt, { force: true })
  await composer.press('Enter')
  await frame('gate').getByTestId('memory-gate-continue').click({ force: true, timeout: 25_000 }).catch(() => {})
}
const idle = async () => {
  const composer = frame('conversation').getByTestId('composer')
  return await composer.isEnabled() && await composer.inputValue() === '' &&
    !(await frame('conversation').getByText('Working…').count())
}
async function shot(id, name) {
  const handle = page.locator(`[data-testid="rack-plugin-frame-${id}"]`)
  await handle.scrollIntoViewIfNeeded()
  await page.waitForTimeout(1500)
  await handle.screenshot({ path: `${out}/${name}.png` })
}
const receipt = { row, run: Number(run), started: new Date().toISOString(), base }

try {
  if (row === 'FL-198') {
    await stage(['Security'])
    receipt.cuts_before = (await json('/v1/rack/query?resource=overwhelm&as_of=now')).data.cuts.length
    await shot('security', `${tag}-security-at-start`)
    await freshThread()
    await send('Using only the bash tool, run exactly this command: cat uv.lock uv.lock — then tell me in one sentence what the tool returned to you.')
    await waitUntil(async () => (await json('/v1/rack/query?resource=overwhelm&as_of=now')).data.cuts.length > receipt.cuts_before, 600_000, 'the query cut')
    await waitUntil(idle, 600_000, 'the query answer')
    await shot('conversation', `${tag}-query`)
    const afterQuery = (await json('/v1/rack/query?resource=overwhelm&as_of=now')).data.cuts.length
    await freshThread()
    await send('Call the delegate_task tool once with share_percent set to 0.1 and this task: "Without using any tools, write about 1,200 words explaining what a memory palace is and how the method of loci works, as your answer." Then tell me in two sentences what came back and whether it had been shortened.')
    await waitUntil(async () => (await json('/v1/rack/query?resource=overwhelm&as_of=now')).data.cuts.slice(afterQuery).some((cut) => cut.kind === 'sub_agent' && cut.action === 'send_back'), 1_200_000, 'the sub-agent send-back')
    await waitUntil(idle, 1_200_000, 'the delegated answer')
    await shot('conversation', `${tag}-subagent`)
    const overwhelm = (await json('/v1/rack/query?resource=overwhelm&as_of=now')).data
    receipt.new_cuts = overwhelm.cuts.slice(receipt.cuts_before)
    receipt.cuts_after = overwhelm.cuts.length
    receipt.bounds = overwhelm.bounds
    // The module follows the selected thread: the delegated one, whose cuts it must list.
    const delegated = receipt.new_cuts.find((cut) => cut.kind === 'sub_agent').thread_id
    receipt.delegated_thread_cuts = overwhelm.cuts.filter((cut) => cut.thread_id === delegated).length
    await waitUntil(async () => (await frame('security').locator('[data-testid="security-cuts"] tbody tr[data-action]').count()) >= receipt.delegated_thread_cuts, 60_000, 'the Security rows')
    await shot('security', `${tag}-security`)
    receipt.security_rows = await frame('security').locator('[data-testid="security-cuts"] tbody tr[data-action]').count()
    receipt.pass = receipt.new_cuts.some((cut) => cut.kind === 'query' && cut.action === 'cut') &&
      receipt.new_cuts.some((cut) => cut.kind === 'sub_agent' && cut.action === 'send_back') &&
      receipt.security_rows >= receipt.delegated_thread_cuts
  }
  if (row === 'FL-184') {
    const nocturne = '/private/tmp/m3hw-final/harness/.venv/bin/nocturne'
    const at = new Date(Date.now() + 150_000)
    const recipe = (name, cron) => {
      const path = `${out}/receipts/${tag}-${name}.json`
      writeFileSync(path, JSON.stringify({
        name: `${tag}-${stamp} ${name}`, prompt: 'Run `python3 -c "print(6*7)"` with the bash tool and answer with its output only.',
        folder: '/private/tmp/m3hw-walk/project/harness', model_policy: 'pinned:openrouter:minimax/minimax-m3',
        budget_usd: 0.05, exit_condition: 'true', tools: 'pydantic', memory_scope: 'none', ...(cron ? { cron } : {}),
      }, null, 2))
      return execFileSync(nocturne, ['jobs', 'save', path, '--daemon-url', base], { encoding: 'utf8' }).trim()
    }
    receipt.saved = [recipe('scheduled', `${at.getUTCMinutes()} ${at.getUTCHours()} * * *`), recipe('on demand')]
    const mine = (await json('/v1/jobs')).jobs.filter((job) => job.definition.name.startsWith(`${tag}-${stamp}`))
    const demand = mine.find((job) => job.definition.name.endsWith('on demand'))
    receipt.run_now = execFileSync(nocturne, ['jobs', 'run', demand.job_id, '--daemon-url', base], { encoding: 'utf8' }).trim()
    const ids = new Set(mine.map((job) => job.job_id))
    await waitUntil(async () => {
      const runs = (await json('/v1/jobs')).runs.filter((item) => ids.has(item.job_id))
      return new Set(runs.map((item) => item.job_id)).size === 2 && runs.every((item) => item.state !== 'running')
    }, 900_000, 'both jobs ran and settled')
    receipt.jobs = await json('/v1/jobs')
    await stage(['Jobs'])
    // the list runs oldest first; bring this run's own jobs into the capture
    await frame('jobs').getByText(`${tag}-${stamp} scheduled`).scrollIntoViewIfNeeded().catch(() => {})
    await shot('jobs', tag)
    receipt.module_text = (await frame('jobs').locator('body').innerText()).slice(0, 3000)
  }
  if (row === 'FL-133') {
    await stage(['Palace'])
    const bodies = async () => (await frame('palace_nebula').locator('body').innerText()).match(/(\d+) bodies/)?.[1]
    receipt.bodies_at_start = await bodies()
    await shot('palace_nebula', `${tag}-before`)
    const facts = {  // distinct topics per run, so each saves as its own memory, never a reinforcement
      1: ['The Nocturne soak sampled CPU every ten minutes for four hours.',
        'Test palaces are made with nocturne palace new and dropped whole afterwards.',
        'The Farm draws folders as chambers and files as cells.'],
      2: ['The supervisor journal records every worker heartbeat as an event.',
        'A rack module receives the latest snapshot within one hundred milliseconds.',
        'An answer keeps at most one hundred stream events in the page.'],
      3: ['Doctor warns once Nocturne uses more than a tenth of the machine memory.',
        'The Security module lists every cut and send-back across restarts.',
        'Symphony worktrees go once their result is kept on the branch.'],
      // runs 4-6 (final build): topics never saved on this palace, since a repeat is reinforced
      4: ['The walk project clone lives under the m3hw-walk scratch folder.',
        'Headless Chrome draws the Palace with Metal and WebGPU switches.',
        'The row driver listens on port 9557 for walk scripts.'],
      5: ['Frozen law copies sit in each product docs folder.',
        'The garden flag file numbers each entry in square brackets.',
        'The Memory test suite needs two testcontainers variables under colima.'],
      6: ['A doctor alarm stops a stalled run after six hundred seconds.',
        'Release targets always name a full commit hash.',
        'The final soak home sits under the m3hw-final-soak folder.'],
      7: ['Captures of the Jobs list scroll to the run under test.',
        'Pre-rebase evidence lives in its own folder beside the final captures.',
        'A gcloud watcher ends only the doctor child calls it started.'],
      8: ['The Palace module counts bodies in its status line.',
        'Each walk writes one receipt per run into the receipts folder.',
        'The capture profile for jobs is separate from the walk profile.'],
    }[run]
    receipt.arrivals = []
    for (const fact of facts) {
      await freshThread()
      const sent = Date.now()
      const before = Number(await bodies() ?? 0)
      await send(`/remember ${fact}`)
      await waitUntil(async () => Number(await bodies() ?? 0) > before, 180_000, 'a new body in the open Palace module')
      receipt.arrivals.push({ fact, seconds: Math.round((Date.now() - sent) / 1000), bodies: await bodies() })
    }
    await shot('palace_nebula', `${tag}-after`)
    receipt.curation = (await json('/v1/visualization?as_of=now&known=all')).curation
    receipt.progress = (await json('/v1/visualization?as_of=now&known=all')).progress
  }
  if (row === 'M3W5B-13') {
    // A small Symphony in its own clean project: when its result is kept, its worktrees go and
    // each attempt's commit stays under refs/nocturne/symphonies/ (SYMPHONY_WORKTREES_KEPT=0).
    const project = process.env.WALK_PROJECT ?? '/private/tmp/m3hw-walk/project/harness'
    const git = (...args) => execFileSync('git', ['-C', project, ...args], { encoding: 'utf8' }).trim()
    receipt.dirty_before = git('status', '--porcelain')
    await stage([])
    await frame('threads').getByTestId('new-thread').click({ force: true })
    await frame('threads').locator('#thread-workspace-root').fill(project, { force: true })
    await frame('threads').getByRole('button', { name: /^create$/i }).click({ force: true })
    await page.waitForTimeout(3000)
    await send('take this to a symphony')
    const card = frame('conversation').getByTestId('symphony-deliberation').last()
    await card.waitFor({ state: 'visible', timeout: 180_000 })
    const field = (name) => card.getByLabel(name, { exact: true }).first()
    await field('Desired outcome').fill('README.md gains one line under its first heading: "Soak note: measured by M3HW."')
    await field('Why this deserves a Symphony').fill('Two attempts and three judges prove a small edit lands and its worktrees are removed after.')
    await field('Step 1').fill('Add the line "Soak note: measured by M3HW." right after the first heading of README.md')
    await field('Done when').fill('README.md contains that exact line after its first heading and no other file changed')
    const stratagems = card.getByLabel(/Stratagems/)
    if (await stratagems.count()) await stratagems.fill('Direct: edit README.md\nCheck first: read README.md, then edit')
    const judges = card.locator('.symphony-judge')
    for (const [index, seat] of ['motivation', 'implementation', 'performance'].entries()) {
      const judge = judges.nth(index)
      await judge.getByLabel('Rubric', { exact: true }).fill('The README has exactly the requested line after its first heading')
      await judge.getByLabel('Required evidence', { exact: true }).fill('git diff of README.md')
      if (seat === 'performance') await judge.getByLabel('Precalculated metric', { exact: true }).fill('one line added, zero lines removed')
    }
    for (const [label, value] of Object.entries({ Attempts: 2, 'Spend USD': 0.8, Rounds: 2, Depth: 0, 'Children / attempt': 0, Minutes: 45 })) {
      await field(label).fill(String(value))
    }
    await card.locator('.symphony-sign input').check({ force: true })
    await card.getByRole('button', { name: /Sign & run/ }).click({ force: true })
    receipt.launched = new Date().toISOString()
    const worktrees = `${project}/.nocturne-worktrees`
    let peak = 0
    await waitUntil(async () => {
      const text = await frame('conversation').locator('body').innerText()
      if (execFileSync('sh', ['-c', `[ -d ${worktrees} ] && du -sk ${worktrees} | cut -f1 || echo 0`], { encoding: 'utf8' }).trim() !== '0')
        peak = Math.max(peak, Number(execFileSync('sh', ['-c', `du -sk ${worktrees} | cut -f1`], { encoding: 'utf8' }).trim()))
      return /Symphony complete|\bBlocked\b/.test(text)
    }, 3_000_000, 'the Symphony to finish')
    await page.waitForTimeout(15000)  // its workers stop, then the removal runs
    await shot('conversation', `${tag}-result`)
    receipt.result_text = (await frame('conversation').getByTestId('symphony-result').last().innerText().catch(() => '')).slice(0, 1500)
    receipt.blocked_text = /\bBlocked\b/.test(await frame('conversation').locator('body').innerText())
    receipt.worktrees_peak_kb = peak
    receipt.worktrees_after = execFileSync('sh', ['-c', `ls ${worktrees} 2>/dev/null || true`], { encoding: 'utf8' }).trim()
    receipt.refs = git('for-each-ref', '--format=%(refname) %(objectname:short)', 'refs/nocturne')
    receipt.git_worktrees = git('worktree', 'list')
    receipt.readme_head = git('log', '-1', '--format=%h %s')
    receipt.symphony_id = receipt.result_text.match(/[0-9A-HJKMNP-TV-Z]{26}/)?.[0] ?? null
    receipt.pass = Boolean(receipt.symphony_id) && peak > 0 &&
      !receipt.worktrees_after.split('\n').includes(receipt.symphony_id) &&
      receipt.refs.includes(`refs/nocturne/symphonies/${receipt.symphony_id}/`)
  }
} catch (error) {
  receipt.error = String(error?.stack ?? error).slice(0, 2000)
  await page.screenshot({ path: `${out}/${tag}-error.png` }).catch(() => {})
} finally {
  receipt.finished = new Date().toISOString()
  writeFileSync(`${out}/receipts/${tag}.json`, `${JSON.stringify(receipt, null, 2)}\n`)
  await context.close()
}
console.log(JSON.stringify({ row, run, pass: receipt.pass ?? null, error: receipt.error ?? null }))
