import type { RackActionType } from './rack'

export type CustomRackModuleId = `plugin:${string}`
export interface CustomRackPlugin {
  id: CustomRackModuleId
  name: string
  html: string
  streams: string[]
  actions: RackActionType[]
  bindings: string[]
}
const STORAGE_KEY = 'nocturne.rack.plugins.v1'

/** FL-105: validate user-authored bundles at the rack capability boundary. */
export function parseRackPlugin(value: unknown): CustomRackPlugin {
  const input = value as Partial<CustomRackPlugin> | null
  if (!input || typeof input.id !== 'string' || !/^plugin:[a-z0-9][a-z0-9-]*$/.test(input.id)
      || typeof input.name !== 'string' || !input.name.trim()
      || typeof input.html !== 'string' || !input.html.trim()
      || !Array.isArray(input.streams) || !input.streams.every((item) => typeof item === 'string')
      || !Array.isArray(input.actions) || !input.actions.every((item) => ['parameter.write', 'rack.scope.get', 'rack.scope.set'].includes(item))
      || (input.bindings !== undefined && (!Array.isArray(input.bindings) || !input.bindings.every((item) => typeof item === 'string')))) {
    throw new Error('Plugin JSON needs id (plugin:name), name, html, streams and actions.')
  }
  return { id: input.id as CustomRackModuleId, name: input.name, html: input.html, streams: input.streams, actions: input.actions, bindings: input.bindings ?? [] }
}

function loadPlugins(): CustomRackPlugin[] {
  if (typeof localStorage === 'undefined') return []
  try {
    const values: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    return Array.isArray(values) ? values.map(parseRackPlugin) : []
  } catch { return [] }
}
export const installedRackPlugins = loadPlugins()

export function saveRackPlugin(plugin: CustomRackPlugin) {
  const plugins = [...installedRackPlugins.filter((item) => item.id !== plugin.id), plugin]
  localStorage.setItem(STORAGE_KEY, JSON.stringify(plugins))
  installedRackPlugins.splice(0, installedRackPlugins.length, ...plugins)
}

export function rackPluginDocument(plugin: CustomRackPlugin): string {
  // WALL credentials / ADR018: custom code uses only the existing MessagePort capability.
  return '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data: blob:; connect-src \'none\'; form-action \'none\'">' + plugin.html
}
