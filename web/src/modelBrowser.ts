import { formatHumanCount, formatHumanUsd } from './humanNumbers.ts'

/** FL-202: one source model as the browser lists it; prices are USD per million tokens. */
export interface ListedModel {
  model: string
  name: string
  context_tokens: number | null
  prompt_price: string | null
  completion_price: string | null
  score: string | null
  reasoning: boolean
  /** SD-079: the request parameters the source says it takes; null when unpublished. */
  parameters?: string[] | null
}

export interface Configuration {
  policy: string
  model: string | null
  reason: string
}

export interface ModelBrowser {
  local?: { url: string | null, model: string | null, when_offline: boolean }
  models: ListedModel[]
  configurations: Configuration[]
  pins: string[]
  chat_policy: string
  current: { model: string, effort: string | null, policy?: string | null } | null
  unavailable?: string
}

export type SortKey = 'rank' | 'price' | 'context'

export function parseBrowser(value: unknown): ModelBrowser {
  if (!isRecord(value) || !Array.isArray(value.models) || !Array.isArray(value.configurations) || !Array.isArray(value.pins)) {
    throw new TypeError('The model list returned an invalid shape')
  }
  return value as unknown as ModelBrowser
}

/** FL-202: pins on top, then the chosen order; rank is a display order, never routing (A-020). */
export function browseOrder(models: ListedModel[], pins: string[], search: string, sort: SortKey): ListedModel[] {
  const needle = search.trim().toLowerCase()
  const number = (value: string | null, missing: number) => value === null ? missing : Number(value)
  const key = (item: ListedModel) => sort === 'price'
    ? number(item.prompt_price, Infinity)
    : sort === 'context' ? -(item.context_tokens ?? -1) : -number(item.score, -Infinity)
  return models
    .filter((item) => needle === '' || item.name.toLowerCase().includes(needle) || item.model.toLowerCase().includes(needle))
    .sort((left, right) => Number(pins.includes(right.model)) - Number(pins.includes(left.model))
      || key(left) - key(right) || left.name.localeCompare(right.name))
}

export function formatPrice(item: Pick<ListedModel, 'prompt_price' | 'completion_price'>): string {
  if (item.prompt_price === null || item.completion_price === null) return '—'
  if (Number(item.prompt_price) === 0 && Number(item.completion_price) === 0) return 'free'
  return `${formatHumanUsd(item.prompt_price)} · ${formatHumanUsd(item.completion_price)}`
}

export function policyName(policy: string): string {
  const [kind, value] = [policy.split(':')[0], policy.slice(policy.indexOf(':') + 1)]
  const name = kind.charAt(0).toUpperCase() + kind.slice(1)
  return kind === 'floor' ? `${name} ${value}` : kind === 'budget' ? `${name} $${value}/h` : name
}

/** FL-206: the strategy a thread's resolution names, in the rail's words; null when the daemon
 * restored the model without its original strategy (hydrated) or nothing has chosen yet. */
export function strategyName(policy: string | null | undefined): string | null {
  if (policy == null || policy === 'hydrated_unverified') return null
  if (policy === 'human_command') return 'Pinned'
  if (policy === 'local_when_offline') return 'Local when offline'
  return policyName(policy)
}

/** FL-206: what each strategy means, in one sentence; the card beside it says what it picks now. */
export function strategyMeaning(policy: string): string {
  const [kind, value] = [policy.split(':')[0], policy.slice(policy.indexOf(':') + 1)]
  switch (kind) {
    case 'pinned': return 'Keeps one model until you change it.'
    case 'max': return 'The highest score in the catalog, whatever it costs.'
    case 'elbow': return 'Where paying more stops buying much more intelligence.'
    case 'floor': return `The cheapest model scoring at least ${value}.`
    case 'slope': return `The last frontier step worth $${value}/M per point.`
    case 'budget': return `The smartest model the measured hourly burn buys for $${value} an hour.`
    case 'local_when_offline': return 'When the broker cannot be reached, a model on this machine takes the turn.'
    default: return ''
  }
}

/** SD-077: the agent policy is in force here while this conversation runs on its pick (or has none yet). */
export function policyInForce(
  browser: Pick<ModelBrowser, 'chat_policy' | 'configurations'>, model: string | null,
): Configuration | null {
  // FL-205: the Pinned card keeps the browsed conversation's model; a pinned policy picks its own.
  const configuration = browser.configurations.find((item) => item.policy === browser.chat_policy) ??
    (browser.chat_policy.startsWith('pinned:')
      ? { policy: browser.chat_policy, model: browser.chat_policy.slice('pinned:'.length), reason: 'keeps this model' }
      : undefined)
  return configuration !== undefined && (model === null || configuration.model === model) ? configuration : null
}

/** SD-079: a parameter descriptor (model.top_k) is offered when the model takes it, or nobody says. */
export function takesParameter(parameters: string[] | null | undefined, descriptorId: string): boolean {
  return parameters == null || parameters.includes(descriptorId.replace(/^model\./u, ''))
}

/** The source's "Provider: Model" names lose the provider; the tip carries the full id. */
export function shortName(name: string): string {
  return name.replace(/^[^:]+:\s*/u, '')
}

export function modelLabel(model: string | null): string {
  return model === null ? '—' : model.slice(model.indexOf(':') + 1)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** FL-205 / FL-206: one model mark wherever a thread is named — the strategy that chose it, the
 * model and its thinking level; the conversation chip (`full`) adds the context window and the
 * price. A thread's own strategy (`policy`, from its resolution) comes first; before it has one
 * the agent policy in force names what it will start on. */
export function modelMark(
  browser: Pick<ModelBrowser, 'chat_policy' | 'configurations' | 'models'> | null,
  model: string | null,
  effort: string | null,
  full = false,
  policy: string | null = null,
): string {
  // SD-077: before the first answer a conversation names what it will start on.
  const inForce = browser === null ? null : policyInForce(browser, model)
  const shown = model ?? inForce?.model ?? null
  const entry = browser?.models.find((item) => item.model === shown)
  const parts = chipParts(shown, entry, effort)
  const mark = full ? parts : parts.slice(0, entry?.reasoning ? 2 : 1)
  const strategy = strategyName(policy) ?? (inForce === null ? null : policyName(inForce.policy))
  return (strategy === null ? mark : [strategy, ...mark]).join(' · ')
}

/** The thinking level the browser read for one conversation, when it names the model shown. */
export function currentEffort(browser: ModelBrowser | null, model: string | null): string | null {
  const shown = model ?? (browser === null ? null : policyInForce(browser, model)?.model ?? null)
  return browser?.current?.model === shown ? browser.current.effort : null
}

/** FL-205: a listed thread's mark — the selected one from its live model and the browser's read
 * (the catalog poll skips it), every other one from the catalog. */
export function threadModelMark(
  browser: ModelBrowser | null,
  entry: { model?: string | null, effort?: string | null, policy?: string | null },
  selected: { model: string | null } | null,
): string {
  const model = selected === null ? entry.model ?? null : selected.model
  const live = selected !== null && browser?.current != null
  const effort = live ? currentEffort(browser, model) : entry.effort ?? null
  return modelMark(browser, model, effort, false, live ? currentStrategy(browser, model) : entry.policy)
}

/** FL-206: the strategy the browser read for one conversation, when it names the model shown. */
export function currentStrategy(browser: ModelBrowser | null, model: string | null): string | null {
  return browser?.current?.model === model ? browser.current.policy ?? null : null
}

/** FL-206: the model summary — one plain paragraph for the model in use: what it is, its price
 * in and out, context, rank, thinking level, and which strategy chose it and why (the readout),
 * with the time the choice stuck (M3SK). Prices come from the listing, as the chip's do. */
export function modelSummary(input: {
  model: string | null
  entry: ListedModel | undefined
  models: ListedModel[]
  effort: string | null
  policy: string | null
  explanation: string | null | undefined
  since: string | null
}): string {
  const { model, entry, models, effort, policy, explanation, since } = input
  if (model === null) return 'No model yet: the first turn chooses one.'
  const name = entry === undefined ? modelLabel(model) : shortName(entry.name)
  const provider = entry?.name.includes(':') ? entry.name.slice(0, entry.name.indexOf(':')) : null
  const facts: string[] = []
  if (entry !== undefined && entry.prompt_price !== null && entry.completion_price !== null) {
    facts.push(formatPrice(entry) === 'free' ? 'free'
      : `${formatHumanUsd(entry.prompt_price)} in and ${formatHumanUsd(entry.completion_price)} out per million tokens`)
  }
  if (entry?.context_tokens != null) facts.push(`a ${formatHumanCount(entry.context_tokens)}-token context`)
  if (entry?.score != null) {
    const ranked = browseOrder(models.filter((item) => item.score !== null), [], '', 'rank')
    const rank = ranked.findIndex((item) => item.model === entry.model) + 1
    facts.push(`score ${entry.score}${rank > 0 ? ` (ranked ${rank} of ${ranked.length})` : ''}`)
  }
  if (entry?.reasoning) facts.push(`${effort ?? 'default'} thinking`)
  const sentences = [`${name}${provider === null ? '' : ` by ${provider}`}${facts.length === 0 ? '' : `: ${facts.join(', ')}`}.`]
  const strategy = strategyName(policy)
  let why = explanation?.trim().replace(/\.$/u, '') ?? ''
  // The readout opens with the strategy's own name ("Elbow: …", "Pinned model …"); said once.
  if (strategy !== null && why.toLowerCase().startsWith(strategy.split(' ')[0].toLowerCase())) {
    why = why.includes(': ') ? why.slice(why.indexOf(': ') + 2) : ''
  }
  if (strategy !== null) sentences.push(`Chosen by ${strategy}${why ? ` — ${why}` : ''}${since === null ? '' : `, since ${since}`}.`)
  else if (why) sentences.push(`${why}${since === null ? '' : `, since ${since}`}.`)
  return sentences.join(' ')
}

/** FL-202: the conversation chip reads model · thinking level · context window · price. */
export function chipParts(model: string | null, entry: ListedModel | undefined, effort: string | null): string[] {
  if (model === null) return ['Choosing model']
  const parts = [entry === undefined ? modelLabel(model) : shortName(entry.name)]
  if (entry === undefined) return parts
  if (entry.reasoning) parts.push(`${effort ?? 'default'} thinking`)
  if (entry.context_tokens !== null) parts.push(`${formatHumanCount(entry.context_tokens)} context`)
  if (entry.prompt_price !== null && entry.completion_price !== null) {
    parts.push(formatPrice(entry) === 'free' ? 'free'
      : `${formatHumanUsd(entry.prompt_price)}/${formatHumanUsd(entry.completion_price)} per M`)
  }
  return parts
}
