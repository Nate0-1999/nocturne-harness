import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { JsonValue } from './protocol'
import { RACK_MANIFESTS, useRackPlugin, useRackSnapshot } from './rack'

type ParameterValue = string | number | null

interface Descriptor {
  id: string
  label: string
  type: 'model' | 'number' | 'integer' | 'option'
  range: { minimum: number; maximum: number; step: number | null } | null
  options: string[]
  default: ParameterValue
  scope: 'thread'
  authority: 'free-journaled' | 'law-bound'
}

interface Change {
  event_id: string
  parameter_id: string
  timestamp: string
  old_value: ParameterValue
  new_value: ParameterValue
}

interface ParameterSnapshot {
  thread_id: string
  as_of: string
  resolved_model: string
  descriptors: Descriptor[]
  values: Record<string, ParameterValue>
  changes: Change[]
}

export function ModelDevice() {
  const snapshot = useRackSnapshot()
  const { events, query } = useRackPlugin()
  const threadId = snapshot.selectedThreadId
  const [scope, setScope] = useState<'ATTUNED' | 'GLOBAL'>(
    RACK_MANIFESTS.model_device.default_scope,
  )
  const [live, setLive] = useState<ParameterSnapshot | null>(null)
  const [view, setView] = useState<ParameterSnapshot | null>(null)
  const [historyIndex, setHistoryIndex] = useState(0)
  const [drafts, setDrafts] = useState<Record<string, number>>({})
  const [slug, setSlug] = useState('')
  const [status, setStatus] = useState('Ready')
  const slugDirty = useRef(false)

  const load = useCallback(async (asOf: string | null = null) => {
    if (threadId === null) {
      setLive(null)
      setView(null)
      return
    }
    try {
      const result = await query.query({
        resource: 'parameters',
        thread_id: threadId,
        as_of: asOf ?? 'now',
      })
      const parsed = parseSnapshot(result.data)
      setView(parsed)
      if (asOf !== null || !slugDirty.current) setSlug(parsed.resolved_model)
      if (asOf === null) {
        setLive(parsed)
        setHistoryIndex(parsed.changes.length)
      }
      setStatus(asOf === null ? 'Live' : `Reviewing ${formatTime(parsed.as_of)}`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Model controls are unavailable')
    }
  }, [query, threadId])

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'model_device' }).then(setScope)
  }, [events])

  useEffect(() => {
    const initial = globalThis.setTimeout(() => { void load() }, 0)
    const unsubscribe = events.subscribe(() => { void load() })
    return () => {
      globalThis.clearTimeout(initial)
      unsubscribe()
    }
  }, [events, load])

  async function write(parameterId: string, value: ParameterValue) {
    if (threadId === null || scope !== 'ATTUNED') return
    setStatus('Applying…')
    try {
      await events.dispatch({
        type: 'parameter.write',
        thread_id: threadId,
        parameter_id: parameterId,
        value,
      })
      if (parameterId === 'model.slug') slugDirty.current = false
      await load()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Control write was refused')
    }
  }

  async function scrub(index: number) {
    setHistoryIndex(index)
    if (live === null || index >= live.changes.length) {
      setView(live)
      if (live !== null) setSlug(live.resolved_model)
      slugDirty.current = false
      setStatus('Live')
      return
    }
    const first = live.changes[0]
    const asOf = index === 0
      ? new Date(Date.parse(first.timestamp) - 1).toISOString()
      : live.changes[index - 1].timestamp
    await load(asOf)
  }

  const editable = scope === 'ATTUNED' && historyIndex === (live?.changes.length ?? 0)
  const descriptors = useMemo(
    () => view?.descriptors ?? live?.descriptors ?? [],
    [live?.descriptors, view?.descriptors],
  )
  const numeric = useMemo(
    () => descriptors.filter((item) => item.type === 'number' || item.type === 'integer'),
    [descriptors],
  )
  const effort = descriptors.find((item) => item.id === 'model.effort')

  return (
    <section className="model-device" aria-labelledby="model-device-title">
      <header className="model-device__header">
        <div>
          <h2 id="model-device-title">Model device</h2>
        </div>
      </header>

      <div className="model-device__truth">
        <span>Model in use</span>
        <strong data-testid="model-device-resolved">{view?.resolved_model ?? 'Waiting for thread'}</strong>
        <small>{scope === 'GLOBAL' ? 'Provider defaults · read only' : status}</small>
      </div>

      <form
        className="model-device__selector"
        onSubmit={(event) => {
          event.preventDefault()
          void write('model.slug', slug)
        }}
      >
        <label htmlFor="model-device-slug">OpenRouter model</label>
        <input
          id="model-device-slug"
          value={slug}
          disabled={!editable}
          onChange={(event) => {
            slugDirty.current = true
            setSlug(event.target.value)
          }}
          spellCheck={false}
        />
        <button
          type="button"
          disabled={!editable || slug.trim().length === 0}
          onClick={() => { void write('model.slug', slug) }}
        >
          Resolve
        </button>
      </form>

      <div className="model-device__controls">
        {numeric.map((descriptor) => {
          const current = scope === 'GLOBAL' ? descriptor.default : view?.values[descriptor.id] ?? null
          const range = descriptor.range!
          const draft = drafts[descriptor.id] ?? (
            typeof current === 'number' ? current : range.minimum
          )
          return (
            <div className="model-knob" key={descriptor.id} data-parameter-id={descriptor.id}>
              <label htmlFor={`control-${descriptor.id}`}>{descriptor.label}</label>
              <output>{typeof current === 'number' ? current : 'Inherit'}</output>
              <input
                id={`control-${descriptor.id}`}
                type="range"
                min={range.minimum}
                max={range.maximum}
                step={range.step ?? 1}
                value={draft}
                disabled={!editable}
                onChange={(event) => {
                  const next = Number(event.target.value)
                  setDrafts((values) => ({ ...values, [descriptor.id]: next }))
                  void write(descriptor.id, next)
                }}
              />
              <button type="button" disabled={!editable || current === null} onClick={() => { void write(descriptor.id, null) }}>
                Inherit
              </button>
            </div>
          )
        })}

        {effort !== undefined && (
          <label className="model-effort" htmlFor="model-device-effort">
            <span>Reasoning effort</span>
            <select
              id="model-device-effort"
              disabled={!editable}
              value={String(scope === 'GLOBAL' ? effort.default ?? '' : view?.values[effort.id] ?? '')}
              onChange={(event) => { void write(effort.id, event.target.value || null) }}
            >
              <option value="">Inherit</option>
              {effort.options.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
          </label>
        )}
      </div>

      <div className="model-device__history">
        <label htmlFor="model-device-history">Control history</label>
        <input
          id="model-device-history"
          type="range"
          min={0}
          max={live?.changes.length ?? 0}
          value={historyIndex}
          disabled={scope === 'GLOBAL' || (live?.changes.length ?? 0) === 0}
          onChange={(event) => { void scrub(Number(event.target.value)) }}
        />
        <span>{historyIndex === (live?.changes.length ?? 0) ? 'Now' : `${historyIndex} / ${live?.changes.length ?? 0}`}</span>
      </div>

      <p className="model-device__note">
        Every accepted turn is journaled. Defaults inherit the provider; no decorative controls.
      </p>
    </section>
  )
}

function parseSnapshot(value: JsonValue | null): ParameterSnapshot {
  if (!isRecord(value) || !Array.isArray(value.descriptors) || !Array.isArray(value.changes) || !isRecord(value.values)) {
    throw new TypeError('Parameter registry returned an invalid snapshot')
  }
  if (typeof value.thread_id !== 'string' || typeof value.as_of !== 'string' || typeof value.resolved_model !== 'string') {
    throw new TypeError('Parameter registry returned incomplete thread truth')
  }
  return value as unknown as ParameterSnapshot
}

function isRecord(value: unknown): value is Record<string, JsonValue> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function formatTime(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
