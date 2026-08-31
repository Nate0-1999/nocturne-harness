import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

/** PLAN M2MI/P1.5 keeps discovery an explicit offer and reuses the ordinary consent queue. */
test('agent-file jump-start offers one explicit route into ordinary seed review', async () => {
  const [app, rack] = await Promise.all([source('App.tsx'), source('rack.tsx')])

  assert.match(rack, /case 'seed\.jump-start\.load':[\s\S]*fetchJson\('\/v1\/seeds\/jump-start'\)/u)
  assert.match(app, /Start with your agent files/u)
  assert.match(app, /Queue for review/u)
  assert.match(app, /type:\s*'seed\.upload',[\s\S]*batch_uid:\s*file\.batch_uid/u)
  assert.match(app, /Nothing entered your Palace\./u)
  assert.doesNotMatch(app, /data-testid="palace-queue-launch"/u)
})

/** P1.5 requires M2MI Memory Ingest to inherit ordinary Stage chrome and geometry. */
test('Memory Ingest is a movable panel rather than a header control or lifecycle overlay', async () => {
  const [app, rack, stage] = await Promise.all([
    source('App.tsx'),
    source('rack.tsx'),
    source('stageLayout.ts'),
  ])

  assert.match(rack, /palace_queue:[\s\S]*name:\s*'Memory Ingest'[\s\S]*slot:\s*'panel'[\s\S]*movable:\s*true/u)
  assert.match(stage, /'memory_graph', 'palace_nebula', 'injection_console', 'palace_queue'/u)
  assert.doesNotMatch(app, /palace_queue:\s*'rack-overlay-module--/u)
})

/** A-059 keeps judged Symphony winners inside the existing explicit-consent queue. */
test('judged Symphony batches reuse Palace Queue and retain explicit owner consent', async () => {
  const [app, rack] = await Promise.all([source('App.tsx'), source('rack.tsx')])

  assert.match(rack, /birthplace\?: 'thread' \| 'seed' \| 'symphony' \| 'curator'/u)
  assert.match(app, /card\.birthplace === 'seed' \|\| card\.birthplace === 'symphony' \|\| card\.birthplace === 'curator'/u)
  assert.match(app, /Judged Symphony winner/u)
  assert.match(app, /explicit consent still required/u)
  assert.match(app, /type: 'queue\.batch\.decide'/u)
})

/** M3CU keeps model judgment visible while all corpus changes require an owner tap. */
test('curator proposals expose Palace activity and use only explicit queue decisions', async () => {
  const [app, rack, palaceState] = await Promise.all([
    source('App.tsx'), source('rack.tsx'), source('PalaceStateModule.tsx'),
  ])

  assert.match(rack, /case 'curation\.load':[\s\S]*fetchJson\('\/v1\/curation'\)/u)
  assert.match(rack, /palace_state:[\s\S]*actions: \['curation\.load'\]/u)
  assert.match(palaceState, /aria-label="Curator activity"/u)
  assert.match(palaceState, /writes or.*removals/u)
  assert.match(app, /Curators never change memories without this queue/u)
  assert.match(app, /card\.proposal_payload\?\.rationale/u)
  assert.match(app, /approval_mode: 'explicit'/u)
  assert.match(app, /actor_class: 'human'/u)
  assert.match(app, /Keep as is/u)
  assert.match(app, /Approve repair/u)
})
