import type { DeckStack } from './SymphonyDeck'

export function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

export function deckCount(stacks: Pick<DeckStack, 'state'>[], waiting: number, lessonIds: Set<string>, pending: string[] | null) {
  const count = stacks.length + waiting
  const parts = [`${count} ${count === 1 ? 'card' : 'cards'}`]
  if (waiting) parts.push(`${waiting} waiting`)
  for (const state of ['running', 'blocked', 'completed'] as const) {
    const amount = stacks.filter(stack => stack.state === state).length
    if (amount) parts.push(`${amount} ${state === 'running' ? 'live' : state}`)
  }
  if (lessonIds.size && pending === null) parts.push('Lesson count unavailable')
  const lessons = pending?.filter(id => lessonIds.has(id)).length
  if (lessons) parts.push(`${lessons} ${lessons === 1 ? 'lesson' : 'lessons'} waiting`)
  return parts.join(' · ')
}

export function attemptOutcome(attempt: DeckStack['attempts'][number], evidence: DeckStack['evidence']) {
  if (attempt.state !== 'stopped') return attempt.state
  for (const entry of evidence) {
    if (!Array.isArray(entry.attempt_lineage)) continue
    for (const item of entry.attempt_lineage) {
      const lineage = record(item)
      if (lineage?.attempt_id !== attempt.attempt_id || !attempt.partial_evidence.includes(String(lineage.artifact_root))) continue
      const status = record(lineage.distillate)?.status
      if (status === 'completed' || status === 'failed' || status === 'cancelled' || status === 'blocked') return status
    }
  }
  return attempt.state
}

export function deckEvidence(entries: DeckStack['evidence']): DeckStack['evidence'] {
  const seen = new Set<string>()
  return entries.flatMap(entry => {
    if (!Array.isArray(entry.verdicts)) return [entry]
    const verdicts = entry.verdicts.filter(value => {
      const id = record(value)?.judge_session_id
      if (typeof id !== 'string') return true
      if (seen.has(id)) return false
      seen.add(id)
      return true
    })
    return verdicts.length ? [{ ...entry, verdicts }] : []
  })
}
