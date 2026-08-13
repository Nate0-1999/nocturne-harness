import type { ConnectionStatus } from './store.ts'

export type PalaceStatus = 'checking' | 'ready' | 'unavailable'

/** F045 keeps transport state distinct from the Palace health stated to the owner. */
export function ownerConnectionCopy(
  connection: ConnectionStatus,
  palace: PalaceStatus,
): string {
  switch (connection) {
    case 'connected':
      if (palace === 'ready') return 'Palace ready'
      if (palace === 'unavailable') return 'Palace unavailable'
      return 'Checking Palace'
    case 'connecting':
      return 'Starting Nocturne'
    case 'reconnecting':
      return 'Reconnecting'
    default:
      return 'Nocturne offline'
  }
}
