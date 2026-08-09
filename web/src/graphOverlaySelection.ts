import type { RackModuleId, RackSelection } from './rack'

export function rackDrawerModule(selection: RackSelection): RackModuleId | null {
  if (selection?.kind === 'memory') {
    return 'memory_graph'
  }
  return selection?.kind === 'module' ? selection.id : null
}

export function rackModuleSelectionIsOpen(
  selection: RackSelection,
  moduleId: RackModuleId,
): boolean {
  return rackDrawerModule(selection) === moduleId
}
