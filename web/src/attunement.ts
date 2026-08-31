import type { RackScope } from './rackLayout'
import type { StageLayoutSet, StageModuleLayout } from './stageLayout'

export const ATTUNEMENT_PICKS_STORAGE_KEY = 'nocturne.stage.attunement-picks.v1'

export interface AttunementThread {
  thread_id: string
  title: string
}

export type AttunementTarget =
  | {
      kind: 'thread'
      id: string
      name: string
      thread_ids: [string]
      source_instance_id: string
    }
  | {
      kind: 'stack'
      id: string
      name: string
      thread_ids: string[]
      source_instance_id: string
    }

export interface StickyAttunementPick {
  layout_signature: string
  source_instance_id: string
}

export interface AttunementTiePick {
  consumer_instance_id: string
  source_instance_id: string
  target: AttunementTarget
  tied_source_instance_ids: string[]
  layout_signature: string
}

export interface AttunementResolution {
  targets: Map<string, AttunementTarget | null>
  sticky_picks: Record<string, StickyAttunementPick>
  new_tie_picks: AttunementTiePick[]
}

export function loadStickyAttunementPicks(
  storage: Storage,
): Record<string, StickyAttunementPick> {
  let value: unknown
  try {
    value = JSON.parse(storage.getItem(ATTUNEMENT_PICKS_STORAGE_KEY) ?? '{}')
  } catch {
    return {}
  }
  if (!isRecord(value)) return {}
  const picks: Record<string, StickyAttunementPick> = {}
  for (const [instanceId, pick] of Object.entries(value)) {
    if (
      isRecord(pick) &&
      typeof pick.layout_signature === 'string' &&
      typeof pick.source_instance_id === 'string'
    ) {
      picks[instanceId] = {
        layout_signature: pick.layout_signature,
        source_instance_id: pick.source_instance_id,
      }
    }
  }
  return picks
}

export function persistStickyAttunementPicks(
  storage: Storage,
  picks: Readonly<Record<string, StickyAttunementPick>>,
): void {
  storage.setItem(ATTUNEMENT_PICKS_STORAGE_KEY, JSON.stringify(picks))
}

interface LocatedSource {
  module: StageModuleLayout
  layer_index: number
  target: AttunementTarget
}

/** PLAN M3AT / D.2 138-139: placement is the binding over x, y, and tab order. */
export function resolveAttunements(
  layout: StageLayoutSet,
  threads: readonly AttunementThread[],
  selectedThreadId: string | null,
  stickyPicks: Readonly<Record<string, StickyAttunementPick>> = {},
  random: () => number = Math.random,
): AttunementResolution {
  const signature = attunementLayoutSignature(layout)
  const threadById = new Map(threads.map((thread) => [thread.thread_id, thread]))
  const threadIds = threads.map((thread) => thread.thread_id)
  const sources: LocatedSource[] = []
  const locatedModules: Array<{ module: StageModuleLayout; layer_index: number }> = []

  layout.layers.forEach((layer, layerIndex) => {
    for (const module of layer.modules) {
      locatedModules.push({ module, layer_index: layerIndex })
      const target = sourceTarget(module, threadById, threadIds, selectedThreadId)
      if (target !== null) sources.push({ module, layer_index: layerIndex, target })
    }
  })

  const targets = new Map<string, AttunementTarget | null>()
  const nextSticky: Record<string, StickyAttunementPick> = {}
  const newTiePicks: AttunementTiePick[] = []

  for (const located of locatedModules) {
    const scope = layout.scopes[located.module.instance_id]
      ?? layout.scopes[located.module.module_id]
      ?? 'ATTUNED'
    if (scope === 'GLOBAL') {
      targets.set(located.module.instance_id, null)
      continue
    }
    const ownSource = sources.find(
      (source) => source.module.instance_id === located.module.instance_id,
    )
    if (ownSource !== undefined) {
      targets.set(located.module.instance_id, ownSource.target)
      continue
    }
    if (sources.length === 0) {
      targets.set(located.module.instance_id, null)
      continue
    }

    const distances = sources.map((source) => ({
      source,
      distance: euclideanDistance(located, source),
    }))
    const minimum = Math.min(...distances.map((candidate) => candidate.distance))
    const tied = distances
      .filter((candidate) => Math.abs(candidate.distance - minimum) < 1e-9)
      .map((candidate) => candidate.source)
      .sort((left, right) => left.module.instance_id.localeCompare(right.module.instance_id))
    let winner = tied[0]
    if (tied.length > 1) {
      const previous = stickyPicks[located.module.instance_id]
      const retained = previous?.layout_signature === signature
        ? tied.find((source) => source.module.instance_id === previous.source_instance_id)
        : undefined
      if (retained !== undefined) {
        winner = retained
      } else {
        const bounded = Math.max(0, Math.min(0.999999999999, random()))
        winner = tied[Math.floor(bounded * tied.length)]
        newTiePicks.push({
          consumer_instance_id: located.module.instance_id,
          source_instance_id: winner.module.instance_id,
          target: winner.target,
          tied_source_instance_ids: tied.map((source) => source.module.instance_id),
          layout_signature: signature,
        })
      }
      nextSticky[located.module.instance_id] = {
        layout_signature: signature,
        source_instance_id: winner.module.instance_id,
      }
    }
    targets.set(located.module.instance_id, winner.target)
  }
  return { targets, sticky_picks: nextSticky, new_tie_picks: newTiePicks }
}

export function attunementBadge(scope: RackScope, target: AttunementTarget | null): string {
  if (scope === 'GLOBAL') return 'Global'
  return target?.name ?? 'Unattuned'
}

export function attunementLayoutSignature(layout: StageLayoutSet): string {
  return JSON.stringify(layout.layers.map((layer) => ({
    layer_id: layer.layer_id,
    modules: layer.modules.map((module) => ({
      instance_id: module.instance_id,
      module_id: module.module_id,
      source_thread_id: module.source_thread_id ?? null,
      conversation_mode: module.conversation_mode ?? null,
      x: module.x,
      y: module.y,
      width: module.width,
      height: module.height,
    })),
  })))
}

function sourceTarget(
  module: StageModuleLayout,
  threadById: ReadonlyMap<string, AttunementThread>,
  threadIds: string[],
  selectedThreadId: string | null,
): AttunementTarget | null {
  if (module.module_id === 'conversation' && module.conversation_mode === 'focused') {
    const threadId = module.source_thread_id ?? selectedThreadId
    const thread = threadId === null ? undefined : threadById.get(threadId)
    return thread === undefined ? null : {
      kind: 'thread',
      id: thread.thread_id,
      name: thread.title,
      thread_ids: [thread.thread_id],
      source_instance_id: module.instance_id,
    }
  }
  if (module.module_id === 'threads') {
    if (threadIds.length === 0) return null
    return {
      kind: 'stack',
      id: 'channel-stack',
      name: 'Channel Stack',
      thread_ids: [...threadIds],
      source_instance_id: module.instance_id,
    }
  }
  if (module.module_id === 'conversation' && module.conversation_mode === 'stack') {
    if (threadIds.length === 0) return null
    return {
      kind: 'stack',
      id: 'the-deck',
      name: 'The Deck',
      thread_ids: [...threadIds],
      source_instance_id: module.instance_id,
    }
  }
  return null
}

function euclideanDistance(
  consumer: { module: StageModuleLayout; layer_index: number },
  source: LocatedSource,
): number {
  const x = consumer.module.x - source.module.x
  const y = consumer.module.y - source.module.y
  const tab = consumer.layer_index - source.layer_index
  return Math.hypot(x, y, tab)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
