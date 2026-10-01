import { useEffect, useState } from 'react'

/** M3W5B-38 / F140 (owner ruling, 2026-09-30: "seen clears it"): an answer seen in a Focused
 * conversation leaves the Deck, which keeps only answers that arrived while the owner was
 * elsewhere. Remembered in this browser; module frames share one origin, so they share it. */
const SEEN_KEY = 'nocturne.deck.seen.v1'
const SEEN_LIMIT = 500

export function readSeenProposals(): Set<string> {
  try {
    const value: unknown = JSON.parse(globalThis.localStorage.getItem(SEEN_KEY) ?? '[]')
    return new Set(Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : [])
  } catch {
    return new Set()
  }
}

export function markProposalSeen(proposalRunId: string): void {
  try {
    const seen = [...readSeenProposals()].filter((id) => id !== proposalRunId)
    seen.push(proposalRunId)
    globalThis.localStorage.setItem(SEEN_KEY, JSON.stringify(seen.slice(-SEEN_LIMIT)))
  } catch {
    // A browser that denies storage keeps the card on the Deck.
  }
}

export function useSeenProposals(): ReadonlySet<string> {
  const [seen, setSeen] = useState(readSeenProposals)
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === SEEN_KEY) setSeen(readSeenProposals())
    }
    globalThis.addEventListener('storage', onStorage)
    return () => globalThis.removeEventListener('storage', onStorage)
  }, [])
  return seen
}
