import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { JsonValue } from './protocol'
import { RACK_MANIFESTS, useRackPlugin, useRackSnapshot } from './rack'
import { Button, Select, TextField } from './kit'
import { formatHumanCount } from './humanNumbers'
import {
  browseOrder, currentEffort, currentStrategy, formatPrice, modelLabel, modelMark, modelSummary, parseBrowser,
  policyInForce, policyName, shortName, strategyMeaning, strategyName, takesParameter, type Configuration, type ModelBrowser, type SortKey,
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

/** FL-205: the model list, the policies and this conversation's model, read again on every change. */
// eslint-disable-next-line react-refresh/only-export-components -- the chip's read, shared with the thread list and the Deck
export function useModelBrowser(threadId: string | null, model: string | null): ModelBrowser | null {
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
  return browser
}

/** FL-202 / FL-206: the conversation's model chip, strategy first; it opens the Model Device. */
export function ModelChip({ browser, model }: { browser: ModelBrowser | null, model: string | null }) {
  return modelMark(browser, model, currentEffort(browser, model), true, currentStrategy(browser, model))
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
  const [localUrl, setLocalUrl] = useState<string | null>(null)
  const parameterDialog = useRef<HTMLDialogElement>(null)

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

  async function write(parameterId: string, value: ParameterValue): Promise<boolean> {
    if (threadId === null || scope !== 'ATTUNED') return false
    setStatus('Applying…')
    try {
      await events.dispatch({
        type: 'parameter.write',
        thread_id: threadId,
        parameter_id: parameterId,
        value,
      })
      await load()
      return true
    } catch (error) {
      // ADR-023: a running turn keeps its model; until run.done (receipts included) a switch waits.
      const message = error instanceof Error ? error.message : 'Control write was refused'
      setStatus(message.includes('busy') ? 'Still finishing the last answer — try again in a moment.' : message)
      return false
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
  const effort = descriptors.find((item) => item.id === 'model.effort')
  const resolved = view?.resolved_model ?? null
  const inUse = browser?.models.find((item) => item.model === resolved)
  // SD-079: only the parameters the model in use takes, per the source's catalog.
  const numeric = useMemo(
    () => descriptors.filter((item) => (item.type === 'number' || item.type === 'integer')
      && takesParameter(inUse?.parameters, item.id)),
    [descriptors, inUse?.parameters],
  )
  const pins = useMemo(() => browser?.pins ?? [], [browser?.pins])
  // FL-206: the summary's "since" is the last model change here, else when the thread began (M3SK).
  const since = view?.changes.filter((change) => change.parameter_id === 'model.slug').at(-1)?.timestamp
    ?? snapshot.catalog.find((entry) => entry.thread_id === threadId)?.created_at ?? null
  // F218: the paragraph names the strategy in force while this conversation runs on its pick, as the
  // rail and the chip do; the reason is then the rail's (the daemon's readout explains the thread's own).
  const own = currentStrategy(browser, resolved)
  const inForce = browser === null || browser.current?.model !== resolved ? null : policyInForce(browser, resolved)
  const taken = inForce !== null && policyName(inForce.policy) !== strategyName(own)
  const summary = modelSummary({
    model: resolved, entry: inUse, models: browser?.models ?? [],
    effort: view?.values['model.effort'] == null ? null : String(view.values['model.effort']),
    policy: inForce?.policy ?? own, explanation: taken ? inForce.reason : view?.policy_explanation,
    since: since === null ? null : formatSince(since),
  })
  const localModel = browser?.local?.model == null ? null
    : browser.local.model.startsWith('local:') ? browser.local.model : `local:${browser.local.model}`
  const localPick = browser?.models.find((item) => item.model === localModel)
    ?? browser?.models.find((item) => item.model.startsWith('local:'))
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
    // Switch first: a refused switch leaves both this conversation and the agent policy as they were.
    if (configuration.model !== resolved && !(await write('model.slug', configuration.model))) return
    try {
      await events.dispatch({ type: 'policies.save', role: 'chat', policy: configuration.policy })
      if (configuration.model.startsWith('local:')) {
        await events.dispatch({ type: 'models.local', url: browser?.local?.url ?? null,
          model: configuration.model, when_offline: browser?.local?.when_offline ?? false })
      }
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
        {numeric.length > 0 && (
          <Button
            type="button"
            action="settings"
            data-testid="model-parameters-open"
            data-tooltip-detail="Temperature and the other request settings this model takes."
            onClick={() => parameterDialog.current?.showModal()}
          >
            Parameters
          </Button>
        )}
        {threadId !== null && browser !== null && <p className="model-summary" data-testid="model-summary">{summary}</p>}
        <small>{scope === 'GLOBAL' ? 'Provider defaults · read only' : status}</small>
      </div>

      <div className="model-panel">
      {/* FL-206: the strategies rail — each one's meaning and the model it picks now; the one in
          force is marked; picking one is the same act as before (policies.save for the chat role). */}
      {browser !== null && browser.configurations.length > 0 && (
        <section className="model-configs" aria-label="Strategies">
          <div className="model-row--head" aria-hidden="true"><span>Strategy</span><span>Picks now</span></div>
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
                <span className="model-config__meaning">{strategyMeaning(configuration.policy)}</span>
                <span className="model-config__model">{entry?.name ?? modelLabel(configuration.model)}</span>
                <span className="model-config__price">
                  {configuration.reason.startsWith('falls back') ? 'fallback · ' : ''}
                  {entry === undefined ? '—' : formatPrice(entry)}
                </span>
              </Button>
            )
          })}
          {browser.local !== undefined && (
            <Button
              variant="bare"
              type="button"
              className="model-config"
              aria-pressed={browser.local.when_offline}
              data-testid="model-config-local_when_offline"
              data-tooltip="Local when offline"
              data-tooltip-detail="Switch on or off. Only while OpenRouter cannot be reached; a reachable refusal never switches."
              onClick={() => {
                const local = { url: browser.local?.url ?? null,
                  model: resolved?.startsWith('local:') ? resolved : browser.local?.model ?? null,
                  when_offline: !browser.local?.when_offline }
                setBrowser((current) => current === null ? current : { ...current, local })
                void events.dispatch({ type: 'models.local', ...local }).then(loadBrowser).catch((error) => {
                  setBrowserError(String(error)); void loadBrowser()
                })
              }}
            >
              <span className="model-config__name">Local when offline</span>
              <span className="model-config__meaning">{strategyMeaning('local_when_offline')}</span>
              <span className="model-config__model">{localPick?.name ?? 'No local model running'}</span>
              <span className="model-config__price">{localPick === undefined ? '—' : formatPrice(localPick)}</span>
            </Button>
          )}
        </section>
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
        <div className="model-browser__tools">
          <TextField aria-label="Local model server" placeholder="Local server URL (automatic when blank)"
            value={localUrl ?? browser?.local?.url ?? ''}
            onChange={(event) => setLocalUrl(event.target.value)} />
          <Button type="button" onClick={() => { void events.dispatch({
            type: 'models.local', url: (localUrl ?? browser?.local?.url) || null, model: browser?.local?.model ?? null,
            when_offline: browser?.local?.when_offline ?? false,
          }).then(loadBrowser).catch((error) => setBrowserError(String(error))) }}>Find local models</Button>
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
                  data-tooltip-detail={current ? 'This conversation uses it now.' : 'Use it here and for new conversations, until you change it.'}
                  disabled={!editable || current}
                  onClick={() => { void configure({ policy: `pinned:${item.model}`, model: item.model, reason: 'keeps this model' }) }}
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
      </div>

      <dialog
        ref={parameterDialog}
        className="memory-restore-dialog model-parameters"
        aria-labelledby="model-parameters-title"
        data-testid="model-parameters"
      >
        <h2 id="model-parameters-title">Parameters · {inUse === undefined ? modelLabel(resolved) : shortName(inUse.name)}</h2>
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
        <Button action="close" type="button" data-tooltip-detail="Changes are already applied." onClick={() => parameterDialog.current?.close()}>
          Close
        </Button>
      </dialog>

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

function formatSince(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.valueOf())) return value
  const today = parsed.toDateString() === new Date().toDateString()
  return parsed.toLocaleString([], { ...(today ? {} : { month: 'short', day: 'numeric' }), hour: '2-digit', minute: '2-digit' })
}
