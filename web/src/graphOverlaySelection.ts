import type { RackModuleId, RackSelection } from './rack'

export function rackDrawerModule(selection: RackSelection): RackModuleId | null {
  if (selection?.kind !== 'module') return null
  return selection.id === 'thread_end' || selection.id === 'palace_queue' ||
    selection.id === 'model_device' || selection.id === 'gate'
    ? selection.id
    : null
}

export function rackModuleSelectionIsOpen(
  selection: RackSelection,
  moduleId: RackModuleId,
): boolean {
  return selection?.kind === 'module' && selection.id === moduleId
}
