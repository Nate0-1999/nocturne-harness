import { useCallback, useEffect, useMemo, useState } from 'react'

import type { JsonValue } from './protocol'
import { RACK_MANIFESTS, useRackPlugin, useRackSnapshot } from './rack'
import { Button, Select, TextField } from './kit'
import { formatHumanCount } from './humanNumbers'
import {
  browseOrder, chipParts, formatPrice, modelLabel, parseBrowser, policyName,
  type Configuration, type ModelBrowser, type SortKey,
} from './modelBrowser'

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
  policy_explanation?: string | null
  descriptors: Descriptor[]
  values: Record<string, ParameterValue>
  changes: Change[]
}

/** FL-202: the conversation's model chip; it opens the browser (the Model Device). */
export function ModelChip({ threadId, model }: { threadId: string | null, model: string | null }) {
  const { events } = useRackPlugin()
  const [browser, setBrowser] = useState<ModelBrowser | null>(null)
  const [refresh, setRefresh] = useState(0)
  useEffect(() => events.subscribe((event) => {
    const type = String(event.envelope.type)
    if (type === 'parameter.change' || type === 'model.change') setRefresh((value) => value + 1)
  }), [events])
  useEffect(() => {
    let live = true
    events.dispatch({ type: 'models.load', thread_id: threadId })
      .then((value) => { if (live) setBrowser(parseBrowser(value)) })
      .catch(() => { if (live) setBrowser(null) })
    return () => { live = false }
  }, [events, threadId, model, refresh])
  const entry = browser?.models.find((item) => item.model === model)
  const effort = browser?.current?.model === model ? browser.current.effort : null
  return chipParts(model, entry, effort).join(' · ')
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
  const [status, setStatus] = useState('Ready')
  const [browser, setBrowser] = useState<ModelBrowser | null>(null)
  const [browserError, setBrowserError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<SortKey>('rank')

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

  const liveModel = live?.resolved_model ?? null
  const loadBrowser = useCallback(async () => {
    try {
      setBrowser(parseBrowser(await events.dispatch({ type: 'models.load', thread_id: threadId })))
      setBrowserError(null)
    } catch (error) {
      setBrowserError(error instanceof Error ? error.message : 'The model list is unavailable.')
    }
  }, [events, threadId])

  useEffect(() => {
    const timer = globalThis.setTimeout(() => { void loadBrowser() }, 0)
    return () => globalThis.clearTimeout(timer)
  }, [loadBrowser, liveModel])

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
      await load()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Control write was refused')
    }
  }

  async function scrub(index: number) {
    setHistoryIndex(index)
    if (live === null || index >= live.changes.length) {
      setView(live)
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
  const resolved = view?.resolved_model ?? null
  const inUse = browser?.models.find((item) => item.model === resolved)
  const pins = useMemo(() => browser?.pins ?? [], [browser?.pins])
  const listed = useMemo(
    () => browseOrder(browser?.models ?? [], pins, search, sort),
    [browser?.models, pins, search, sort],
  )

  async function pin(model: string, pinned: boolean) {
    try {
      const result = await events.dispatch({ type: 'models.pin', model, pinned }) as { pins: string[] }
      setBrowser((current) => current === null ? current : { ...current, pins: result.pins })
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Pin was not saved')
    }
  }

  async function configure(configuration: Configuration) {
    if (threadId === null || !editable || configuration.model === null) return
    try {
      await events.dispatch({ type: 'policies.save', role: 'chat', policy: configuration.policy })
      if (configuration.model !== resolved) await write('model.slug', configuration.model)
      await loadBrowser()
      setStatus(`${policyName(configuration.policy)} · new conversations start here too`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Configuration was not saved')
    }
  }

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
        {effort !== undefined && inUse?.reasoning === true && (
          <label className="model-effort" htmlFor="model-device-effort">
            <span>Thinking</span>
            <Select
              id="model-device-effort"
              data-tooltip-detail="How long the model may think before answering."
              disabled={!editable}
              value={String(scope === 'GLOBAL' ? effort.default ?? '' : view?.values[effort.id] ?? '')}
              onChange={(event) => { void write(effort.id, event.target.value || null) }}
            >
              <option value="">Default</option>
              {effort.options.map((option) => <option key={option} value={option}>{option}</option>)}
            </Select>
          </label>
        )}
        {view?.policy_explanation && <p>{view.policy_explanation}</p>}
        <small>{scope === 'GLOBAL' ? 'Provider defaults · read only' : status}</small>
      </div>

      {browser !== null && browser.configurations.length > 0 && (
        <div className="model-configs" role="group" aria-label="Standard configurations">
          {browser.configurations.map((configuration) => {
            const entry = browser.models.find((item) => item.model === configuration.model)
            return (
              <Button
                variant="bare"
                type="button"
                key={configuration.policy}
                className="model-config"
                aria-pressed={configuration.policy === browser.chat_policy}
                data-testid={`model-config-${configuration.policy.split(':')[0]}`}
                data-tooltip={policyName(configuration.policy)}
                data-tooltip-detail={`Use it here and for new conversations; ${configuration.reason}.`}
                disabled={!editable || configuration.model === null}
                onClick={() => { void configure(configuration) }}
              >
                <span className="model-config__name">{policyName(configuration.policy)}</span>
                <span className="model-config__model">{entry?.name ?? modelLabel(configuration.model)}</span>
                <span className="model-config__price">
                  {configuration.reason.startsWith('falls back') ? 'fallback · ' : ''}
                  {entry === undefined ? '—' : formatPrice(entry)}
                </span>
              </Button>
            )
          })}
        </div>
      )}

      <section className="model-browser" aria-label="Models">
        <div className="model-browser__tools">
          <TextField
            type="search"
            aria-label="Search models"
            data-tooltip-detail="Filter by name or id."
            placeholder="Search models"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            spellCheck={false}
          />
          <Select
            aria-label="Sort models"
            data-tooltip-detail="Rank is the benchmark score the policies use; it orders the list, it never picks for you."
            value={sort}
            onChange={(event) => setSort(event.target.value as SortKey)}
          >
            <option value="rank">Rank</option>
            <option value="price">Price</option>
            <option value="context">Context</option>
          </Select>
          <span>{browserError ?? browser?.unavailable ?? `${listed.length} models`}</span>
        </div>
        <div className="model-row model-row--head" aria-hidden="true">
          <span>Model</span><span>Score</span><span>$/M in · out</span><span>Context</span><span />
        </div>
        <ul data-testid="model-browser-list">
          {listed.map((item) => {
            const pinned = pins.includes(item.model)
            const current = item.model === resolved
            return (
              <li key={item.model} className={current ? 'model-row model-row--current' : 'model-row'}>
                <Button
                  variant="bare"
                  type="button"
                  className="model-row__pick"
                  data-model={item.model}
                  data-tooltip={item.model}
                  data-tooltip-detail={current ? 'This conversation uses it now.' : 'Switch this conversation to it from the next turn.'}
                  disabled={!editable || current}
                  onClick={() => { void write('model.slug', item.model) }}
                >
                  <span className="model-row__name">{item.name}{item.reasoning && <small> · thinks</small>}</span>
                  <span>{item.score ?? '—'}</span>
                  <span>{formatPrice(item)}</span>
                  <span>{item.context_tokens === null ? '—' : formatHumanCount(item.context_tokens)}</span>
                </Button>
                <Button
                  type="button"
                  iconOnly
                  action={pinned ? 'unpin' : 'pin'}
                  aria-pressed={pinned}
                  data-tooltip={pinned ? 'Unpin' : 'Pin to top'}
                  data-tooltip-detail={pinned ? 'Return it to its ranked place.' : 'Keep it at the top of this list.'}
                  onClick={() => { void pin(item.model, !pinned) }}
                >
                  {pinned ? 'Unpin' : 'Pin'}
                </Button>
              </li>
            )
          })}
        </ul>
      </section>

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
                data-tooltip-detail="Drag to set; the value is journaled with the next turn."
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
              <Button type="button" data-tooltip={`Inherit ${descriptor.label}`} data-tooltip-detail="Clear this value and use the provider's default." disabled={!editable || current === null} onClick={() => { void write(descriptor.id, null) }}>
                Inherit
              </Button>
            </div>
          )
        })}

      </div>

      <div className="model-device__history">
        <label htmlFor="model-device-history">Control history</label>
        <input
          id="model-device-history"
          type="range"
          data-tooltip-detail="Scrub back through this conversation's control changes."
          min={0}
          max={live?.changes.length ?? 0}
          value={historyIndex}
          disabled={scope === 'GLOBAL' || (live?.changes.length ?? 0) === 0}
          onChange={(event) => { void scrub(Number(event.target.value)) }}
        />
        <span>{historyIndex === (live?.changes.length ?? 0) ? 'Now' : `${historyIndex} / ${live?.changes.length ?? 0}`}</span>
      </div>

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
