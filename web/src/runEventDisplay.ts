import type { JsonObject } from './protocol'

export function elideBinaryPayload(key: string, value: unknown): unknown {
  if (value !== null && typeof value === 'object' && 'kind' in value &&
      value.kind === 'binary' && 'media_type' in value && 'data' in value &&
      typeof value.data === 'string') {
    const bytes = Math.floor(value.data.length * 3 / 4) - (value.data.match(/=+$/)?.[0].length ?? 0)
    return `… <${String(value.media_type)}, ${Math.ceil(bytes / 1024)} KB>`
  }
  if (key === 'data_base64' && typeof value === 'string') return '… <binary payload>'
  return value
}

export function browserScreenshotDataUrl(event: JsonObject): string | null {
  if (event.event_kind !== 'function_tool_result') return null
  const part = event.part
  if (part === null || Array.isArray(part) || typeof part !== 'object') return null
  if (part.tool_name !== 'screenshot' || !Array.isArray(event.content)) return null
  for (const value of event.content) {
    if (value === null || Array.isArray(value) || typeof value !== 'object') continue
    if (
      value.kind === 'binary' &&
      typeof value.media_type === 'string' &&
      value.media_type.startsWith('image/') &&
      typeof value.data === 'string'
    ) {
      // Pydantic emits URL-safe base64; data URLs require the standard alphabet.
      return `data:${value.media_type};base64,${value.data.replaceAll('-', '+').replaceAll('_', '/')}`
    }
  }
  return null
}
