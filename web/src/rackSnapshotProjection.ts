import type { RackSnapshot } from './rack'

const PRIVATE_IMAGE_KEYS = new Set([
  'data_base64',
  'image_input',
  'image_preview_data_url',
  'local_filename',
])

/** Remove browser-local image bytes and names before a snapshot crosses into any rack iframe. */
export function rackSnapshotForIframe(snapshot: RackSnapshot): RackSnapshot {
  return rackValueForIframe(snapshot)
}

/** Keep private image material out of every message crossing the rack iframe boundary. */
export function rackValueForIframe<Value>(value: Value): Value {
  return stripPrivateImageFields(value) as Value
}

function stripPrivateImageFields(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(stripPrivateImageFields)
  }
  if (typeof value !== 'object' || value === null) {
    return value
  }
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => !PRIVATE_IMAGE_KEYS.has(key))
      .map(([key, item]) => [key, stripPrivateImageFields(item)]),
  )
}
