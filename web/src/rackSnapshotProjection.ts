import type { RackSnapshot } from './rack'

const PRIVATE_IMAGE_KEYS = new Set([
  'data_base64',
  'image_input',
  'image_preview_data_url',
  'local_filename',
])

/** Remove browser-local image bytes and names before a snapshot crosses into any rack iframe. */
export function rackSnapshotForIframe(snapshot: RackSnapshot): RackSnapshot {
  return projectStoreValue(snapshot) as RackSnapshot
}

// M3HW: each store change re-copied every thread's messages and events once per module frame.
// The store replaces values and never edits one in place, so a value projected once stays
// projected: a change now costs the objects it replaced, not the whole rack.
const projectedStoreValues = new WeakMap<object, unknown>()

function projectStoreValue(value: unknown): unknown {
  if (typeof value !== 'object' || value === null) {
    return value
  }
  const cached = projectedStoreValues.get(value)
  if (cached !== undefined) {
    return cached
  }
  const projected = Array.isArray(value)
    ? value.map(projectStoreValue)
    : Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !PRIVATE_IMAGE_KEYS.has(key))
        .map(([key, item]) => [key, projectStoreValue(item)]),
    )
  projectedStoreValues.set(value, projected)
  return projected
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
