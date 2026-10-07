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
  models: ListedModel[]
  configurations: Configuration[]
  pins: string[]
  chat_policy: string
  current: { model: string, effort: string | null } | null
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
  return kind === 'floor' ? `${name} ${value}` : name
}

/** SD-077: the agent policy is in force here while this conversation runs on its pick (or has none yet). */
export function policyInForce(
  browser: Pick<ModelBrowser, 'chat_policy' | 'configurations'>, model: string | null,
): Configuration | null {
  const configuration = browser.configurations.find((item) => item.policy === browser.chat_policy)
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

/** FL-205: one model mark wherever a thread is named — the policy in force, the model and its
 * thinking level; the conversation chip (`full`) adds the context window and the price. */
export function modelMark(
  browser: Pick<ModelBrowser, 'chat_policy' | 'configurations' | 'models'> | null,
  model: string | null,
  effort: string | null,
  full = false,
): string {
  // SD-077: before the first answer a conversation names what it will start on.
  const policy = browser === null ? null : policyInForce(browser, model)
  const shown = model ?? policy?.model ?? null
  const entry = browser?.models.find((item) => item.model === shown)
  const parts = chipParts(shown, entry, effort)
  const mark = full ? parts : parts.slice(0, entry?.reasoning ? 2 : 1)
  return (policy === null ? mark : [policyName(policy.policy), ...mark]).join(' · ')
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
  entry: { model?: string | null, effort?: string | null },
  selected: { model: string | null } | null,
): string {
  const model = selected === null ? entry.model ?? null : selected.model
  const effort = selected !== null && browser?.current != null
    ? currentEffort(browser, model)
    : entry.effort ?? null
  return modelMark(browser, model, effort)
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
