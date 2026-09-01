import type { AttunementTarget } from './attunement'
import type { RackAction } from './rack'

const THREAD_ACTIONS = new Set<RackAction['type']>([
  'prompt.submit',
  'run.cancel',
  'thread.archive',
  'memory.refresh',
  'memory.add',
  'memory.remove',
  'memory.edit',
  'memory.pin',
  'parameter.write',
])

/** Return the attuned thread that must become authoritative before this action. */
export function attunedThreadSelection(
  actionType: RackAction['type'],
  attunement: AttunementTarget | null,
  selectedThreadId: string | null,
): string | null {
  return attunement?.kind === 'thread' &&
    attunement.id !== selectedThreadId &&
    THREAD_ACTIONS.has(actionType)
    ? attunement.id
    : null
}
