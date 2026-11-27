import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { JsonValue } from './protocol'
import type { CountryFilters, CountryRule, ListedModel } from './modelBrowser'
import { RACK_MANIFESTS, useRackPlugin, useRackSnapshot } from './rack'
import { Button, Select, TextField } from './kit'
import { formatHumanCount } from './humanNumbers'
import { failureMessage, serverMessage } from './requestFailure'
import { attachModelPinHold } from './modelPinHold'
import {
  browseOrder, currentEffort, currentStrategy, formatPrice, modelLabel, modelMark, modelSummary, parseBrowser,
  policyInForce, policyName, shortName, strategyMeaning, strategyName, subscriptionGroups, subscriptionState, takesParameter, type Configuration, type ModelBrowser, type SortKey,
} from './modelBrowser'

type ParameterValue = string | number | null

const regions = new Intl.DisplayNames(['en'], { type: 'region' })
function locationList(codes: string[] = [], unknown = false) {
  return [...codes.map(code => regions.of(code)), ...(unknown || !codes.length ? ['Unknown'] : [])].join(', ')
}

function ModelCountries({ item }: { item: ListedModel }) {
  return <small className="model-row__countries">
    Maker {item.maker_country ? regions.of(item.maker_country) : 'Unknown'} · HQ {locationList(item.headquarters, item.unknown_headquarters)} · Datacenters {locationList(item.datacenters, item.unknown_datacenters)}
    {item.country_exclusion && <strong>{item.country_exclusion}</strong>}
  </small>
}

function CountryControls({ filters, options, save }: {
  filters: CountryFilters; options: string[]; save: (filters: CountryFilters) => Promise<void>
}) {
  const [draft, setDraft] = useState(filters)
  const [saving, setSaving] = useState(false)
  const count = filters.maker.countries.length + filters.serving.countries.length
  function update(key: 'maker' | 'serving', rule: Partial<CountryRule>) {
    setDraft(current => ({ ...current, [key]: { ...current[key], ...rule } }))
  }
  return <details className="model-countries">
    <summary>Country filters · {count ? count : 'Off'}</summary>
    <fieldset disabled={saving}>
      {(['maker', 'serving'] as const).map(key => {
        const label = key === 'maker' ? 'Maker country' : 'Provider countries'
        const rule = draft[key]
        return <div key={key}>
          <strong>{label}</strong>
          {key === 'serving' && <small>Applies to the provider’s reported headquarters and datacenters.</small>}
          <div className="country-rule">
            <Select aria-label={label + ' rule'} value={rule.mode} onChange={e => update(key, { mode: e.target.value as CountryRule['mode'] })}>
              <option value="allow">Allow only</option><option value="exclude">Exclude</option>
            </Select>
            <Select aria-label={label + ' to add'} value="" onChange={e => update(key, { countries: [...rule.countries, e.target.value] })}>
              <option value="">Add country</option>
              {options.filter(code => !rule.countries.includes(code)).map(code => <option key={code} value={code}>{regions.of(code)}</option>)}
            </Select>
            {rule.countries.map(code => <Button key={code} action="remove" type="button" aria-label={'Remove ' + regions.of(code) + ' from ' + label} onClick={() => update(key, { countries: rule.countries.filter(c => c !== code) })}>{regions.of(code)}</Button>)}
          </div>
        </div>
      })}
      <label><input type="checkbox" checked={draft.keep_unknown} onChange={e => setDraft({ ...draft, keep_unknown: e.target.checked })} /> Keep unknown countries when filtering</label>
      <Button type="button" disabled={JSON.stringify(draft) === JSON.stringify(filters)} onClick={async () => {
        setSaving(true)
        try { await save(draft) } finally { setSaving(false) }
      }}>Save country filters</Button>
    </fieldset>
  </details>
}

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

/** FL-202 / FL-206: the conversation's model chip, strategy first. */
function ModelChip({ browser, model }: { browser: ModelBrowser | null, model: string | null }) {
  if (!model && browser?.unavailable && !policyInForce(browser, null)?.model) return 'No model available'
  return modelMark(browser, model, currentEffort(browser, model), true, currentStrategy(browser, model))
}

function pickDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function catalogMessage(browser: ModelBrowser): string | undefined {
  if (browser.last_pick && browser.using_saved_pick) {
    const what = browser.chat_policy === 'elbow' ? 'Best value' : 'Last pick'
    return `${what} found on ${pickDate(browser.last_pick.checked)}. The catalog cannot be read now.`
  }
  return browser.unavailable
}

function StrategyReadout({ browser }: { browser: ModelBrowser }) {
  const choice = policyInForce(browser, null)
  const id = choice?.model ?? browser.last_pick?.model ?? null
  const entry = browser.models.find((item) => item.model === id)
  return <div className="model-strategy-readout">
    <small>New conversations</small>
    <strong>{policyName(browser.chat_policy)} · {entry ? shortName(entry.name) : id ? modelLabel(id) : 'No pick yet'}</strong>
    <p>{strategyMeaning(browser.chat_policy)}</p>
    {browser.requested_policy && browser.requested_policy !== browser.chat_policy && <p>Your pinned model is banned. This strategy chooses while the ban is in place.</p>}
    {browser.last_pick && <small>Pick last changed {pickDate(browser.last_pick.changed)}</small>}
    {browser.last_pick && !browser.unavailable && <small>Offline pick saved {pickDate(browser.last_pick.checked)}</small>}
    {browser.unavailable && <p role="status">{catalogMessage(browser)}</p>}
  </div>
}

/** SD-101: the conversation header's Model box lists the pinned models. One tap is this
 * conversation's `model.slug` write and nothing else: no policy is saved, so new conversations
 * start where they did. The last row opens the Model Device. */
export function ModelSwitch({ browser, threadId, model, busy, onOpenDevice }: {
  browser: ModelBrowser | null
  threadId: string | null
  model: string | null
  /** ADR-023: a running turn keeps its model, so the rows wait for it. */
  busy: boolean
  onOpenDevice: () => void
}) {
  const { events } = useRackPlugin()
  const [open, setOpen] = useState(false)
  // Pins change in the Model Device, which tells no other module: the list reads them as it opens.
  const [fresh, setFresh] = useState<ModelBrowser | null>(null)
  const [status, setStatus] = useState('')
  const root = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLButtonElement>(null)
  const listed = fresh ?? browser
  const inUse = model ?? listed?.current?.model ?? null
  const choices = [...new Set([...(inUse?.startsWith('subscription:') ? [inUse] : []), ...(listed?.pins ?? [])])]

  useEffect(() => {
    if (!open) return
    const away = (event: Event) => {
      if (!(event.target instanceof Node && root.current?.contains(event.target))) setOpen(false)
    }
    document.addEventListener('pointerdown', away)
    globalThis.addEventListener('blur', away)
    return () => {
      document.removeEventListener('pointerdown', away)
      globalThis.removeEventListener('blur', away)
    }
  }, [open])

  function toggle() {
    setOpen(!open)
    setStatus('')
    if (open) return
    events.dispatch({ type: 'models.load', thread_id: threadId })
      .then((value) => setFresh(parseBrowser(value)))
      .catch(() => setFresh(null))
  }

  async function pick(pin: string) {
    if (threadId === null) return
    try {
      await events.dispatch({ type: 'parameter.write', thread_id: threadId, parameter_id: 'model.slug', value: pin })
      setOpen(false)
      box.current?.focus()
    } catch (error) {
      setStatus(failureMessage(error, 'The model was not switched. Wait for the answer to finish and try again.'))
    }
  }

  return (
    <div
      className="model-switch"
      ref={root}
      onKeyDown={(event) => {
        if (event.key !== 'Escape' || !open) return
        setOpen(false)
        box.current?.focus()
      }}
    >
      <Button variant="bare"
        type="button"
        ref={box}
        className="chat-header__model"
        data-testid="active-model"
        aria-label={`Active model: ${inUse ? modelLabel(inUse) : 'being chosen'}`}
        aria-expanded={open}
        data-tooltip="Switch model"
        data-tooltip-detail="Your pinned models, for this conversation only; the last row opens the Model Device."
        onClick={toggle}
      >
        <span aria-hidden="true">Model</span>
        <span className="chat-header__model-value" data-testid="active-model-detail">
          <ModelChip browser={browser} model={model} />
          {!open && browser?.unavailable && <small className="model-switch__outage">{catalogMessage(browser)}</small>}
        </span>
        <span className="chat-header__model-action" aria-hidden="true">Open</span>
      </Button>
      {open && (
        <section className="model-switch__list" aria-label="Pinned models" data-testid="model-switch">
          {listed && <StrategyReadout browser={listed} />}
          <ul>
            {choices.map((pin) => {
              const entry = listed?.models.find((item) => item.model === pin)
              const current = pin === inUse
              return (
                <li key={pin}>
                  <Button variant="bare"
                    type="button"
                    className="model-switch__row"
                    data-model={pin}
                    aria-current={current || undefined}
                    data-tooltip={modelLabel(pin)}
                    data-tooltip-detail={current ? 'This conversation uses it now.'
                      : busy ? 'Wait for the answer to finish.' : 'Use it in this conversation only.'}
                    disabled={current || busy || threadId === null}
                    onClick={() => { void pick(pin) }}
                  >
                    <span className="model-switch__name">{entry === undefined ? modelLabel(pin) : shortName(entry.name)}</span>
                    <span>{current ? 'In use' : pin.startsWith('subscription:') ? 'Included with your plan' : entry === undefined ? '—' : formatPrice(entry)}</span>
                  </Button>
                </li>
              )
            })}
          </ul>
          {status !== '' && <p role="status">{status}</p>}
          {listed !== null && choices.length === 0 && <p>Pin models in the Model Device to list them here.</p>}
          <Button variant="bare"
            type="button"
            className="model-switch__row"
            data-testid="model-switch-device"
            data-tooltip="Open Model Device"
            data-tooltip-detail="Browse, pin and switch models; set the thinking level."
            onClick={() => { setOpen(false); onOpenDevice() }}
          >
            <span className="model-switch__name">All models</span>
            <span>Model Device</span>
          </Button>
        </section>
      )}
    </div>
  )
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
  const [banTarget, setBanTarget] = useState('')
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
      setStatus(failureMessage(error, 'Model controls could not be loaded. Close this device and open it again.'))
    }
  }, [query, threadId])

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'model_device' }).then(setScope)
  }, [events])

  const liveModel = live?.resolved_model ?? null
  const loadBrowser = useCallback(async () => {
    try {
      setBrowser(parseBrowser(await events.dispatch({ type: 'models.load', thread_id: threadId, subscriptions: true, country_details: true })))
      setBrowserError(null)
    } catch (error) {
      setBrowserError(failureMessage(error, 'The model list could not be loaded. Close this device and open it again.'))
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
      const message = failureMessage(error, 'The model control was not saved. Wait for the answer to finish and try again.')
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
  const subscription = resolved?.startsWith('subscription:') === true
  const StrategyRail = subscription ? 'details' : 'section'
  const groups = subscriptionGroups(browser)
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
      setStatus(failureMessage(error, 'The model pin was not saved. Try pinning it again.'))
    }
  }

  async function ban(target: string, banned: boolean) {
    try {
      await events.dispatch({ type: 'models.ban', target, banned })
      setBanTarget('')
      await loadBrowser()
      setStatus(banned ? 'Ban added' : 'Ban lifted')
    } catch (error) {
      setStatus(failureMessage(error, 'The ban could not be saved.'))
    }
  }

  async function configure(configuration: Configuration) {
    if (threadId === null || !editable || configuration.model === null) return
    // Switch first: a refused switch leaves both this conversation and the agent policy as they were.
    if (configuration.model !== resolved && !(await write('model.slug', configuration.model))) return
    if (configuration.model.startsWith('subscription:')) {
      await loadBrowser()
      return
    }
    try {
      await events.dispatch({ type: 'policies.save', role: 'chat', policy: configuration.policy })
      if (configuration.model.startsWith('local:')) {
        await events.dispatch({ type: 'models.local', url: browser?.local?.url ?? null,
          model: configuration.model, when_offline: browser?.local?.when_offline ?? false })
      }
      await loadBrowser()
      setStatus(`${policyName(configuration.policy)} · new conversations start here too`)
    } catch (error) {
      setStatus(failureMessage(error, 'The model configuration was not saved. Check its values and try again.'))
    }
  }

  return (
    <section className="model-device" aria-labelledby="model-device-title">
      <header className="model-device__header">
        <div>
          <h2 id="model-device-title">Model device</h2>
        </div>
      </header>

      {browser && <StrategyReadout browser={browser} />}
      <div className="model-device__truth">
        <span>Model in use</span>
        <strong data-testid="model-device-resolved" title={resolved ?? undefined}>{subscription ? modelLabel(resolved) : inUse ? shortName(inUse.name) : resolved ?? 'No conversation model yet'}</strong>
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
              {(inUse.effort_levels ?? effort.options).map((option) => <option key={option} value={option}>
                {subscription ? option === 'xhigh' ? 'Extra high' : option[0].toUpperCase() + option.slice(1) : option}
              </option>)}
            </Select>
          </label>
        )}
        {subscription && browser && !inUse?.reasoning && <p>{inUse ? 'This tool uses its own thinking setting.' : 'Thinking options are unavailable.'}</p>}
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
        {!subscription && resolved !== null && browser !== null && <details><summary>Model details</summary><p className="model-summary" data-testid="model-summary">{summary}</p></details>}
        {(resolved !== null || !browser?.unavailable) && <small>{scope === 'GLOBAL' ? 'Provider defaults · read only' : status}</small>}
      </div>

      {browser && <section className="model-bans" aria-label="Banned models and makers">
        <h3>Banned models and makers</h3>
        {Object.keys(browser.bans ?? {}).length === 0 && <p>No bans.</p>}
        {Object.entries(browser.bans ?? {}).map(([target, reason]) => <div key={target}>
          <p><strong>{target.replace(/^maker:/u, 'All models by ').replace(/^model:/u, '')}</strong><br />{reason}</p>
          <Button type="button" aria-label={`Lift ban on ${target}`} onClick={() => { void ban(target, false) }}>Lift ban</Button>
        </div>)}
        <div>
          <Select aria-label="Model or maker to ban" value={banTarget} onChange={(event) => setBanTarget(event.target.value)}>
            <option value="">Choose a model or maker</option>
            <optgroup label="Makers">{[...new Set(browser.models.filter((item) => item.model.startsWith('openrouter:')).map((item) => modelLabel(item.model).split('/')[0]))].sort().filter((maker) => !browser.bans?.[`maker:${maker}`]).map((maker) => <option key={maker} value={`maker:${maker}`}>{maker}</option>)}</optgroup>
            <optgroup label="Models">{browser.models.filter((item) => !item.banned_by).map((item) => <option key={item.model} value={`model:${item.model.replace(/^openrouter:/u, '')}`}>{item.name}</option>)}</optgroup>
          </Select>
          <Button type="button" disabled={!banTarget} onClick={() => { void ban(banTarget, true) }}>Add ban</Button>
        </div>
      </section>}
      {browser?.country_error && <p role="status">{browser.country_error}</p>}
      {browser?.country_filters && <CountryControls filters={browser.country_filters} options={browser.country_options ?? []} save={async filters => {
        try {
          await events.dispatch({ type: 'models.countries', filters })
          await loadBrowser()
          setStatus('Country filters saved')
        } catch (error) { setStatus(failureMessage(error, 'The country filters could not be saved.')) }
      }} />}
      <div className={subscription ? 'model-panel model-panel--subscription' : 'model-panel'}>
      {/* FL-206: the strategies rail — each one's meaning and the model it picks now; the one in
          force is marked; picking one is the same act as before (policies.save for the chat role). */}
      <div className="model-rail">
      {subscription && <p className="model-subscription-choice">You chose your subscription for this conversation.</p>}
      {browser !== null && browser.configurations.length > 0 && (
        <StrategyRail className="model-configs" aria-label="Strategies">
          {subscription && <summary title="Show broker strategies">Broker strategies</summary>}
          <div className="model-row--head" aria-hidden="true"><span>Strategy</span><span>Picks now</span></div>
          {browser.configurations.map((configuration) => {
            const entry = browser.models.find((item) => item.model === configuration.model)
            return (
              <Button
                variant="bare"
                type="button"
                key={configuration.policy}
                className="model-config"
                aria-pressed={!subscription && configuration.policy === browser.chat_policy}
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
              aria-pressed={!subscription && browser.local.when_offline}
              data-testid="model-config-local_when_offline"
              data-tooltip="Local when offline"
              data-tooltip-detail="Switch on or off. Only while OpenRouter cannot be reached; a reachable refusal never switches."
              onClick={() => {
                const local = { url: browser.local?.url ?? null,
                  model: resolved?.startsWith('local:') ? resolved : browser.local?.model ?? null,
                  when_offline: !browser.local?.when_offline }
                setBrowser((current) => current === null ? current : { ...current, local })
                void events.dispatch({ type: 'models.local', ...local }).then(loadBrowser).catch((error) => {
                  setBrowserError(failureMessage(error, 'The configuration was not deleted. Try again.')); void loadBrowser()
                })
              }}
            >
              <span className="model-config__name">Local when offline</span>
              <span className="model-config__meaning">{strategyMeaning('local_when_offline')}</span>
              <span className="model-config__model">{localPick?.name ?? 'No local model running'}</span>
              <span className="model-config__price">{localPick === undefined ? '—' : formatPrice(localPick)}</span>
            </Button>
          )}
        </StrategyRail>
      )}

      </div>
      <section ref={attachModelPinHold} className="model-browser" aria-label="Models">
        {groups.length > 0 && <section className="subscription-models" aria-label="Your subscriptions">
          <h3>Your subscriptions</h3>
          <p className="model-pin-hint">Press and hold a model to pin it.</p>
          {groups.map(source => <details key={source.tool} open>
            <summary title={`Show or hide ${source.name} models`}><strong>{source.name}</strong><span>{subscriptionState(source)}</span></summary>
            {source.models.length > 0 && <ul aria-label={source.name}>
              {source.models.map(item => <li key={item.model} className="model-row">
                <Button variant="bare" type="button" className="subscription-pick" data-model={item.model}
                  data-tooltip={modelLabel(item.model)} data-tooltip-detail="Use this plan for this conversation."
                  aria-current={item.model === resolved || undefined} disabled={!editable || item.model === resolved || Boolean(item.banned_by)}
                  onClick={() => { void configure({policy: `pinned:${item.model}`, model: item.model, reason: 'keeps this model'}) }}>
                  <span>{item.model.split('/').slice(2).join('/')}</span><small>Included with your plan</small>
                </Button>
                <Button type="button" iconOnly action={pins.includes(item.model) ? 'unpin' : 'pin'}
                  disabled={Boolean(item.banned_by)} aria-pressed={pins.includes(item.model)} data-tooltip={pins.includes(item.model) ? 'Unpin' : 'Pin model'}
                  data-tooltip-detail="Show this model in the conversation header."
                  onClick={() => { void pin(item.model, !pins.includes(item.model)) }}>
                  {pins.includes(item.model) ? 'Unpin' : 'Pin'}
                </Button>
              </li>)}
            </ul>}
          </details>)}
        </section>}
        {groups.length === 0 && <p className="model-pin-hint">Press and hold a model to pin it.</p>}
        {(!browser?.unavailable || browser.models.length > 0) && <div className="model-browser__tools">
          <TextField
            type="search"
            aria-label="Search models"
            data-tooltip-detail="Filter by name or id."
            placeholder={groups.length ? 'Search broker models' : 'Search models'}
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
          <span>{browserError ?? (browser?.unavailable ? serverMessage(browser.unavailable, 'The model list could not be loaded. Close this device and open it again.') : `${listed.length} models`)}</span>
        </div>}
        <div className="model-browser__tools">
          <TextField aria-label="Local model server" placeholder="Local server URL (automatic when blank)"
            value={localUrl ?? browser?.local?.url ?? ''}
            onChange={(event) => setLocalUrl(event.target.value)} />
          <Button type="button" onClick={() => { void events.dispatch({
            type: 'models.local', url: (localUrl ?? browser?.local?.url) || null, model: browser?.local?.model ?? null,
            when_offline: browser?.local?.when_offline ?? false,
          }).then(loadBrowser).catch((error: unknown) => setBrowserError(failureMessage(error, 'Local models could not be found. Start the local model service and try again.'))) }}>Find local models</Button>
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
                  data-country-excluded={item.country_exclusion ? true : undefined}
                  data-tooltip={item.model}
                  data-tooltip-detail={item.country_exclusion || (current ? 'This conversation uses it now.' : item.model.startsWith('subscription:')
                    ? 'Use this subscription for this conversation.' : 'Use it here and for new conversations, until you change it.')}
                  disabled={!editable || current || Boolean(item.banned_by || item.country_exclusion)}
                  onClick={() => { void configure({ policy: `pinned:${item.model}`, model: item.model, reason: 'keeps this model' }) }}
                >
                  <span className="model-row__name">{item.name}{item.banned_by ? <small> · banned</small> : item.reasoning && <small> · thinks</small>}
                    <ModelCountries item={item} />
                  </span>
                  <span>{item.score ?? '—'}</span>
                  <span>{formatPrice(item)}</span>
                  <span>{item.context_tokens === null ? '—' : formatHumanCount(item.context_tokens)}</span>
                </Button>
                {item.banned_by ? <Button type="button" onClick={() => { void ban(item.banned_by!, false) }}>Lift ban</Button> : <Button
                  type="button"
                  iconOnly
                  action={pinned ? 'unpin' : 'pin'}
                  disabled={!pinned && Boolean(item.country_exclusion)}
                  aria-pressed={pinned}
                  data-tooltip={pinned ? 'Unpin' : 'Pin model'}
                  data-tooltip-detail={pinned ? 'Return it to its ranked place.' : 'Keep it at the top of this list.'}
                  onClick={() => { void pin(item.model, !pinned) }}
                >
                  {pinned ? 'Unpin' : 'Pin'}
                </Button>}
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
              <output>{typeof current === 'number' ? current : 'Default'}</output>
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
              <Button type="button" data-tooltip={`Use the default ${descriptor.label}`} data-tooltip-detail="Clear this value and use the provider's default." disabled={!editable || current === null} onClick={() => { void write(descriptor.id, null) }}>
                Use default
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
