const LEGACY_FIXTURE_TITLES = new Set([
  'Map the release boundary and hold the queue open.',
  'Turn that boundary into three calm checks.',
  'Keep partial work visible while I stop this run.',
  'Show the budget boundary without losing the draft.',
  'Show a recoverable run error with partial work.',
  'Use the H5 verification memories to explain the handoff.',
  'Open the H6 verification thread context.',
  '/remember H8 remembers that Markdown evidence needs readable tables and code.',
  'Show the H8 Markdown proof. Keep **plain-user-text** literal in my message and treat <button data-h8-user-raw="true">unsafe</button> as text.',
].map(normalizedThreadTitle))

// This fingerprint keeps cleanup compatible with catalogs polluted by the retired
// customer-visible fixture title without carrying that phrase in the shipped bundle.
const LEGACY_FIXTURE_TITLE_FINGERPRINTS = new Set(['41:07dfa7514a768599'])

export function normalizedThreadTitle(prompt: string): string {
  const normalized = prompt.trim().replace(/\s+/gu, ' ')
  const codePoints = Array.from(normalized)
  if (codePoints.length <= 48) {
    return normalized
  }
  const candidate = codePoints.slice(0, 48).join('')
  const finalWordBoundary = candidate.lastIndexOf(' ')
  const visible = finalWordBoundary > 0
    ? candidate.slice(0, finalWordBoundary)
    : candidate
  return `${visible}…`
}

function titleFingerprint(title: string): string {
  let hash = 0xcbf29ce484222325n
  for (const character of title) {
    hash ^= BigInt(character.codePointAt(0) ?? 0)
    hash = BigInt.asUintN(64, hash * 0x100000001b3n)
  }
  return `${Array.from(title).length}:${hash.toString(16).padStart(16, '0')}`
}

export function isLegacyFixtureTitle(title: string): boolean {
  const normalized = normalizedThreadTitle(title)
  return LEGACY_FIXTURE_TITLES.has(normalized) ||
    LEGACY_FIXTURE_TITLE_FINGERPRINTS.has(titleFingerprint(normalized))
}

export function visibleThreadTitle(title: string): string {
  const normalized = normalizedThreadTitle(title)
  // FL-205: the journal's title is cut at 80 characters, mid-word; shown, it ends on a whole word.
  return LEGACY_FIXTURE_TITLE_FINGERPRINTS.has(titleFingerprint(normalized))
    ? 'Verification thread'
    : normalized
}

/** M3W6B-53: open threads that share a title are numbered by age, so each reads apart. */
export function distinctThreadTitles(
  entries: readonly { thread_id: string, title: string, created_at: string }[],
): Map<string, string> {
  const groups = new Map<string, { thread_id: string, created_at: string }[]>()
  for (const entry of entries) {
    const title = visibleThreadTitle(entry.title)
    groups.set(title, [...(groups.get(title) ?? []), entry])
  }
  return new Map([...groups].flatMap(([title, group]) => group
    .sort((left, right) => left.created_at.localeCompare(right.created_at) || left.thread_id.localeCompare(right.thread_id))
    .map((entry, index): [string, string] => [entry.thread_id, group.length === 1 ? title : `${title} · ${index + 1}`])))
}
