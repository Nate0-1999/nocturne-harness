import type { Envelope } from './protocol'

export interface RackEnvelopeEvent {
  direction: 'inbound' | 'outbound'
  envelope: Envelope
}

export interface RackResizeEvent {
  module_id: string
  width: number
  height: number
  grid_width: number
  grid_height: number
}

type EnvelopeListener = (event: RackEnvelopeEvent) => void
type ResizeListener = (event: RackResizeEvent) => void

const envelopeListeners = new Set<EnvelopeListener>()
const resizeListeners = new Set<ResizeListener>()

export function publishRackEnvelope(event: RackEnvelopeEvent): void {
  for (const listener of envelopeListeners) {
    listener(event)
  }
}

export function subscribeRackEnvelopes(listener: EnvelopeListener): () => void {
  envelopeListeners.add(listener)
  return () => envelopeListeners.delete(listener)
}

export function publishRackResize(event: RackResizeEvent): void {
  for (const listener of resizeListeners) {
    listener(event)
  }
}

export function subscribeRackResize(listener: ResizeListener): () => void {
  resizeListeners.add(listener)
  return () => resizeListeners.delete(listener)
}
