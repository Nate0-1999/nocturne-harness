const ULID_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
const ULID_PATTERN = /^[0-7][0-9A-HJKMNP-TV-Z]{25}$/i
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const ISO_8601_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/
const MAX_ULID_TIME = 281_474_976_710_655
const MAX_ULID_RANDOM = (1n << 80n) - 1n

let lastUlidTime = -1
let lastUlidRandom = -1n

export const DIRECT_MACHINE_ID = 'direct'

export type JsonPrimitive = boolean | number | string | null
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[]
export type JsonObject = { [key: string]: JsonValue }
export type Ulid = string

export interface Envelope<
  Type extends string = string,
  Payload extends JsonValue = JsonValue,
> {
  v: 1
  id: Ulid
  ts: string
  machine_id: string
  agent_id?: string
  thread_id?: string
  type: Type
  payload: Payload
}

export interface ThreadCatalogEntry {
  thread_id: string
  title: string
  created_at: string
  updated_at: string
}

export type StopReason =
  | 'end_turn'
  | 'cancelled'
  | 'error'
  | 'budget_exceeded'

export type UserMessageState = 'queued' | 'running' | StopReason

export interface UserTranscriptMessage {
  message_id: Ulid
  run_id: Ulid
  role: 'user'
  content: string
  state: UserMessageState
}

export interface AssistantTranscriptMessage {
  message_id: Ulid
  run_id: Ulid
  role: 'assistant'
  content: string
  thinking: string
  events: JsonObject[]
  partial: boolean
}

export type TranscriptMessage = UserTranscriptMessage | AssistantTranscriptMessage

export interface OptimisticUserMessage {
  message_id: Ulid
  run_id: null
  role: 'user'
  content: string
  state: 'submitting'
}

export type ChatMessage = TranscriptMessage | OptimisticUserMessage

export interface Usage {
  requests: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
}

export interface QueuedPrompt {
  run_id: Ulid
  prompt_id: Ulid
  prompt: string
}

export interface ActiveRunSnapshot {
  run_id: Ulid
  prompt_id: Ulid
  state: 'running' | 'waiting_gate' | 'cancelling'
  usage: Usage
  queued: QueuedPrompt[]
}

export type MemoryKind =
  | 'fact'
  | 'preference'
  | 'procedure'
  | 'project_note'
  | 'persona'
  | 'pinned'

export type MemoryStatus = 'active' | 'quarantined' | 'tombstoned'

export type MemoryUnit = JsonObject & {
  memory_id: string
  principal_id: string
  label: string
  body: string
  kind: MemoryKind
  keywords: string[]
  project_key: string | null
  thread_origin: string | null
  origin_path: string | null
  pin: boolean
  status: MemoryStatus
  revision: number
  stats: JsonObject
  bias: number
  embedding_model: string
  created_at: string
  updated_at: string
}

export type MemoryPanelOperation = 'refresh' | 'remove' | 'edit' | 'pin'
export type MemoryPanelResult =
  | 'refreshed'
  | 'removed'
  | 'edited'
  | 'pin_changed'

export type MemoryPanelItem = JsonObject & {
  memory: MemoryUnit
  in_context: boolean
}

export type MemoryPanelRequestPayload =
  | { action: 'refresh' }
  | { action: 'remove'; memory_id: string }
  | {
      action: 'edit'
      memory_id: string
      expected_revision: number
      body: string
    }
  | {
      action: 'pin'
      memory_id: string
      expected_revision: number
      pin: boolean
    }

export type MemoryPanelStatePayload = JsonObject & {
  action: 'state'
  request_id: Ulid
  result: MemoryPanelResult
  items: MemoryPanelItem[]
  total: number
}

export type MemoryPanelConflictPayload = JsonObject & {
  action: 'conflict'
  request_id: Ulid
  operation: 'edit' | 'pin'
  memory: MemoryUnit
  message: string
}

export type MemoryPanelErrorPayload = JsonObject & {
  action: 'error'
  request_id: Ulid
  operation: MemoryPanelOperation
  code: string
  message: string
}

export type MemoryPanelServerPayload =
  | MemoryPanelStatePayload
  | MemoryPanelConflictPayload
  | MemoryPanelErrorPayload

export type MemoryFeatures = JsonObject & {
  sem: number
  kw: number
  time: number
  proj: number
  freq: number
  hist: number
}

export type ScoredMemoryCard = JsonObject & {
  memory_id: string
  label: string
  body: string
  kind: MemoryKind
  pin: boolean
  score: number
  features: MemoryFeatures
  rank: number
}

export type GateStage = 'review' | 'wrong_resolution'

export type GateOpenPayload = JsonObject & {
  run_id: Ulid
  kind: 'memory_gate'
  stage: GateStage
  injection_id: string
  snapshot_ts: string
  scorer_version: string
  injected: ScoredMemoryCard[]
  near_misses: ScoredMemoryCard[]
  wrong_removed: MemoryUnit[]
  resolution_error?: string | null
}

export type RemovalReason = 'not_relevant' | 'wrong' | 'never'

export type RemovedMemoryDecision = JsonObject & {
  memory_id: string
  reason: RemovalReason
}

export type WrongResolutionDecision = JsonObject & {
  memory_id: string
  expected_revision: number
  action: 'edit' | 'expire'
  body?: string
}

export type GateCommitPayload = JsonObject & {
  run_id: Ulid
  injection_id: string
  removed: RemovedMemoryDecision[]
  added_back: string[]
  wrong_resolution?: WrongResolutionDecision
}

export interface ThreadSnapshotPayload {
  messages: TranscriptMessage[]
  open_gate: GateOpenPayload | null
  active_run: ActiveRunSnapshot | null
  resolved_model: string | null
}

export interface RunStartedPayload {
  run_id: Ulid
  prompt_id: Ulid
  resolved_model: string | null
}

export interface PromptQueuedPayload {
  run_id: Ulid
  prompt_id: Ulid
}

export type RunDeltaPayload =
  | { run_id: Ulid; kind: 'text'; text: string }
  | { run_id: Ulid; kind: 'thinking'; text: string }
  | { run_id: Ulid; kind: 'event'; event: JsonObject }

export interface RunUsagePayload extends Usage {
  run_id: Ulid
}

export interface RunDonePayload {
  run_id: Ulid
  stop_reason: StopReason
  partial: boolean
}

export interface GateDismissPayload {
  run_id: Ulid
}

export type DecodedServerEvent =
  | { type: 'thread.snapshot'; payload: ThreadSnapshotPayload }
  | { type: 'run.started'; payload: RunStartedPayload }
  | { type: 'prompt.queued'; payload: PromptQueuedPayload }
  | { type: 'run.delta'; payload: RunDeltaPayload }
  | { type: 'run.usage'; payload: RunUsagePayload }
  | { type: 'run.done'; payload: RunDonePayload }
  | { type: 'gate.open'; payload: GateOpenPayload }
  | { type: 'gate.dismiss'; payload: GateDismissPayload }
  | { type: 'memory.panel.update'; payload: MemoryPanelServerPayload }
  | { type: 'error'; payload: JsonValue }
  | { type: 'unknown'; payload: JsonValue }

export interface BrowserPayloadMap {
  'thread.snapshot': { request: true }
  'prompt.submit': { prompt: string }
  'run.cancel': { run_id: Ulid }
  'gate.commit': GateCommitPayload
  'memory.panel.update': MemoryPanelRequestPayload
}

export type BrowserMessageType = keyof BrowserPayloadMap

function encodeBase32(value: bigint, length: number): string {
  let encoded = ''
  for (let index = 0; index < length; index += 1) {
    encoded = ULID_ALPHABET[Number(value & 31n)] + encoded
    value >>= 5n
  }
  return encoded
}

function random80Bits(): bigint {
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(10))
  let value = 0n
  for (const byte of bytes) {
    value = (value << 8n) | BigInt(byte)
  }
  return value
}

/** Create a process-fresh, monotonically increasing canonical ULID. */
export function newUlid(): Ulid {
  let time = Date.now()
  if (!Number.isSafeInteger(time) || time < 0 || time > MAX_ULID_TIME) {
    throw new RangeError('current time is outside the ULID timestamp range')
  }

  let random: bigint
  if (time > lastUlidTime) {
    random = random80Bits()
  } else {
    time = lastUlidTime
    random = lastUlidRandom + 1n
    if (random > MAX_ULID_RANDOM) {
      time += 1
      if (time > MAX_ULID_TIME) {
        throw new RangeError('ULID space exhausted')
      }
      random = 0n
    }
  }

  lastUlidTime = time
  lastUlidRandom = random
  return encodeBase32(BigInt(time), 10) + encodeBase32(random, 16)
}

export function isUlid(value: unknown): value is Ulid {
  return typeof value === 'string' && ULID_PATTERN.test(value)
}

export function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value)
}

export function createBrowserEnvelope<Type extends BrowserMessageType>(
  type: Type,
  payload: BrowserPayloadMap[Type],
  threadId: string,
  machineId: string = DIRECT_MACHINE_ID,
): Envelope<Type, BrowserPayloadMap[Type]> {
  if (!isUuid(threadId)) {
    throw new TypeError('threadId must be a UUID')
  }
  if (!machineId.trim()) {
    throw new TypeError('machineId must not be blank')
  }
  return {
    v: 1,
    id: newUlid(),
    ts: new Date().toISOString(),
    machine_id: machineId,
    thread_id: threadId,
    type,
    payload,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isJsonObject(value: unknown): value is JsonObject {
  return isRecord(value) && Object.values(value).every(isJsonValue)
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean'
  ) {
    return true
  }
  if (typeof value === 'number') {
    return Number.isFinite(value)
  }
  if (Array.isArray(value)) {
    return value.every(isJsonValue)
  }
  return isJsonObject(value)
}

function isIsoTimestamp(value: unknown): value is string {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value))
}

function isIso8601Timestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    ISO_8601_PATTERN.test(value) &&
    !Number.isNaN(Date.parse(value))
  )
}

export function parseEnvelope(raw: string): Envelope | null {
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }
  if (
    !isRecord(value) ||
    value.v !== 1 ||
    !isUlid(value.id) ||
    !isIsoTimestamp(value.ts) ||
    typeof value.machine_id !== 'string' ||
    (value.agent_id !== undefined && typeof value.agent_id !== 'string') ||
    (value.thread_id !== undefined && typeof value.thread_id !== 'string') ||
    typeof value.type !== 'string' ||
    !value.type.trim() ||
    !isJsonValue(value.payload)
  ) {
    return null
  }
  return value as unknown as Envelope
}

function parseUsage(value: unknown): Usage | null {
  if (
    !isRecord(value) ||
    !Number.isInteger(value.requests) ||
    (value.requests as number) < 0 ||
    !Number.isInteger(value.input_tokens) ||
    (value.input_tokens as number) < 0 ||
    !Number.isInteger(value.output_tokens) ||
    (value.output_tokens as number) < 0 ||
    (value.cache_read_tokens !== undefined &&
      (!Number.isInteger(value.cache_read_tokens) ||
        (value.cache_read_tokens as number) < 0)) ||
    (value.cache_write_tokens !== undefined &&
      (!Number.isInteger(value.cache_write_tokens) ||
        (value.cache_write_tokens as number) < 0))
  ) {
    return null
  }
  return {
    requests: value.requests as number,
    input_tokens: value.input_tokens as number,
    output_tokens: value.output_tokens as number,
    cache_read_tokens: (value.cache_read_tokens as number | undefined) ?? 0,
    cache_write_tokens: (value.cache_write_tokens as number | undefined) ?? 0,
  }
}

function parseQueuedPrompt(value: unknown): QueuedPrompt | null {
  if (
    !isRecord(value) ||
    !isUlid(value.run_id) ||
    !isUlid(value.prompt_id) ||
    typeof value.prompt !== 'string' ||
    !value.prompt.trim()
  ) {
    return null
  }
  return {
    run_id: value.run_id,
    prompt_id: value.prompt_id,
    prompt: value.prompt,
  }
}

function parseActiveRun(value: unknown): ActiveRunSnapshot | null {
  if (!isRecord(value) || !isUlid(value.run_id) || !isUlid(value.prompt_id)) {
    return null
  }
  if (!['running', 'waiting_gate', 'cancelling'].includes(String(value.state))) {
    return null
  }
  const usage = parseUsage(value.usage)
  if (usage === null || !Array.isArray(value.queued)) {
    return null
  }
  const queued = value.queued.map(parseQueuedPrompt)
  if (queued.some((prompt) => prompt === null)) {
    return null
  }
  return {
    run_id: value.run_id,
    prompt_id: value.prompt_id,
    state: value.state as ActiveRunSnapshot['state'],
    usage,
    queued: queued as QueuedPrompt[],
  }
}

const MEMORY_KINDS: readonly MemoryKind[] = [
  'fact',
  'preference',
  'procedure',
  'project_note',
  'persona',
  'pinned',
]
const MEMORY_STATUSES: readonly MemoryStatus[] = [
  'active',
  'quarantined',
  'tombstoned',
]

const FEATURE_KEYS = ['sem', 'kw', 'time', 'proj', 'freq', 'hist'] as const
const CARD_KEYS = [
  'memory_id',
  'label',
  'body',
  'kind',
  'pin',
  'score',
  'features',
  'rank',
] as const
const MEMORY_UNIT_KEYS = [
  'memory_id',
  'principal_id',
  'label',
  'body',
  'kind',
  'keywords',
  'project_key',
  'thread_origin',
  'origin_path',
  'pin',
  'status',
  'revision',
  'stats',
  'bias',
  'embedding_model',
  'created_at',
  'updated_at',
] as const

function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
): boolean {
  const actual = Object.keys(value)
  return actual.length === expected.length && expected.every((key) => key in value)
}

function parseMemoryFeatures(value: unknown): MemoryFeatures | null {
  if (!isRecord(value) || !hasExactKeys(value, FEATURE_KEYS)) {
    return null
  }
  for (const key of FEATURE_KEYS) {
    const feature = value[key]
    if (
      typeof feature !== 'number' ||
      !Number.isFinite(feature) ||
      feature < 0 ||
      feature > 1
    ) {
      return null
    }
  }
  return {
    sem: value.sem as number,
    kw: value.kw as number,
    time: value.time as number,
    proj: value.proj as number,
    freq: value.freq as number,
    hist: value.hist as number,
  }
}

function parseScoredMemoryCard(value: unknown): ScoredMemoryCard | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, CARD_KEYS) ||
    !isUuid(value.memory_id) ||
    typeof value.label !== 'string' ||
    typeof value.body !== 'string' ||
    !MEMORY_KINDS.includes(value.kind as MemoryKind) ||
    typeof value.pin !== 'boolean' ||
    typeof value.score !== 'number' ||
    !Number.isFinite(value.score) ||
    !Number.isInteger(value.rank) ||
    (value.rank as number) < 1
  ) {
    return null
  }
  const features = parseMemoryFeatures(value.features)
  if (features === null) {
    return null
  }
  return {
    memory_id: value.memory_id,
    label: value.label,
    body: value.body,
    kind: value.kind as MemoryKind,
    pin: value.pin,
    score: value.score,
    features,
    rank: value.rank as number,
  }
}

function parseMemoryUnit(value: unknown): MemoryUnit | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, MEMORY_UNIT_KEYS) ||
    !isUuid(value.memory_id) ||
    typeof value.principal_id !== 'string' ||
    typeof value.label !== 'string' ||
    typeof value.body !== 'string' ||
    !MEMORY_KINDS.includes(value.kind as MemoryKind) ||
    !Array.isArray(value.keywords) ||
    !value.keywords.every((keyword) => typeof keyword === 'string') ||
    (value.project_key !== null && typeof value.project_key !== 'string') ||
    (value.thread_origin !== null && typeof value.thread_origin !== 'string') ||
    (value.origin_path !== null && typeof value.origin_path !== 'string') ||
    typeof value.pin !== 'boolean' ||
    !MEMORY_STATUSES.includes(value.status as MemoryStatus) ||
    !Number.isInteger(value.revision) ||
    (value.revision as number) < 1 ||
    !isJsonObject(value.stats) ||
    typeof value.bias !== 'number' ||
    !Number.isFinite(value.bias) ||
    typeof value.embedding_model !== 'string' ||
    !isIso8601Timestamp(value.created_at) ||
    !isIso8601Timestamp(value.updated_at)
  ) {
    return null
  }
  return {
    memory_id: value.memory_id,
    principal_id: value.principal_id,
    label: value.label,
    body: value.body,
    kind: value.kind as MemoryKind,
    keywords: value.keywords as string[],
    project_key: value.project_key as string | null,
    thread_origin: value.thread_origin as string | null,
    origin_path: value.origin_path as string | null,
    pin: value.pin,
    status: value.status as MemoryStatus,
    revision: value.revision as number,
    stats: value.stats,
    bias: value.bias,
    embedding_model: value.embedding_model,
    created_at: value.created_at,
    updated_at: value.updated_at,
  }
}

function parseMemoryPanelItem(value: unknown): MemoryPanelItem | null {
  if (!isRecord(value) || typeof value.in_context !== 'boolean') {
    return null
  }
  const memory = parseMemoryUnit(value.memory)
  if (memory === null) {
    return null
  }
  return {
    ...value,
    memory,
    in_context: value.in_context,
  } as MemoryPanelItem
}

function parseMemoryPanelUpdate(value: unknown): MemoryPanelServerPayload | null {
  if (!isJsonObject(value) || !isUlid(value.request_id)) {
    return null
  }

  if (value.action === 'state') {
    if (
      !['refreshed', 'removed', 'edited', 'pin_changed'].includes(
        String(value.result),
      ) ||
      !Array.isArray(value.items) ||
      !Number.isInteger(value.total) ||
      (value.total as number) < 0
    ) {
      return null
    }
    const items = value.items.map(parseMemoryPanelItem)
    if (items.some((item) => item === null)) {
      return null
    }
    return {
      ...value,
      action: 'state',
      request_id: value.request_id,
      result: value.result as MemoryPanelResult,
      items: items as MemoryPanelItem[],
      total: value.total as number,
    }
  }

  if (value.action === 'conflict') {
    const memory = parseMemoryUnit(value.memory)
    if (
      !['edit', 'pin'].includes(String(value.operation)) ||
      memory === null ||
      typeof value.message !== 'string' ||
      !value.message.trim()
    ) {
      return null
    }
    return {
      ...value,
      action: 'conflict',
      request_id: value.request_id,
      operation: value.operation as 'edit' | 'pin',
      memory,
      message: value.message,
    }
  }

  if (value.action === 'error') {
    if (
      !['refresh', 'remove', 'edit', 'pin'].includes(String(value.operation)) ||
      typeof value.code !== 'string' ||
      !value.code.trim() ||
      typeof value.message !== 'string' ||
      !value.message.trim()
    ) {
      return null
    }
    return {
      ...value,
      action: 'error',
      request_id: value.request_id,
      operation: value.operation as MemoryPanelOperation,
      code: value.code,
      message: value.message,
    }
  }

  return null
}

function parseGateOpen(value: unknown): GateOpenPayload | null {
  if (!isJsonObject(value)) {
    return null
  }
  const stage = value.stage === undefined ? 'review' : value.stage
  const wrongRemovedValue =
    value.wrong_removed === undefined ? [] : value.wrong_removed
  if (
    !isUlid(value.run_id) ||
    value.kind !== 'memory_gate' ||
    !['review', 'wrong_resolution'].includes(String(stage)) ||
    !isUuid(value.injection_id) ||
    !isIso8601Timestamp(value.snapshot_ts) ||
    typeof value.scorer_version !== 'string' ||
    !value.scorer_version.trim() ||
    !Array.isArray(value.injected) ||
    !Array.isArray(value.near_misses) ||
    !Array.isArray(wrongRemovedValue) ||
    (value.resolution_error !== undefined &&
      value.resolution_error !== null &&
      typeof value.resolution_error !== 'string')
  ) {
    return null
  }
  const injected = value.injected.map(parseScoredMemoryCard)
  const nearMisses = value.near_misses.map(parseScoredMemoryCard)
  const wrongRemoved = wrongRemovedValue.map(parseMemoryUnit)
  if (
    injected.some((card) => card === null) ||
    nearMisses.some((card) => card === null) ||
    wrongRemoved.some((unit) => unit === null)
  ) {
    return null
  }
  const memoryIds = [
    ...(injected as ScoredMemoryCard[]),
    ...(nearMisses as ScoredMemoryCard[]),
  ].map((card) => card.memory_id)
  if (new Set(memoryIds).size !== memoryIds.length) {
    return null
  }
  if (
    (stage === 'review' && wrongRemoved.length !== 0) ||
    (stage === 'wrong_resolution' &&
      (injected.length !== 0 || nearMisses.length !== 0 || wrongRemoved.length !== 1))
  ) {
    return null
  }
  return {
    ...value,
    run_id: value.run_id,
    kind: 'memory_gate',
    stage: stage as GateStage,
    injection_id: value.injection_id,
    snapshot_ts: value.snapshot_ts,
    scorer_version: value.scorer_version,
    injected: injected as ScoredMemoryCard[],
    near_misses: nearMisses as ScoredMemoryCard[],
    wrong_removed: wrongRemoved as MemoryUnit[],
    resolution_error:
      value.resolution_error === undefined
        ? null
        : (value.resolution_error as string | null),
  }
}

function parseTranscriptMessage(value: unknown): TranscriptMessage | null {
  if (!isRecord(value) || !isUlid(value.message_id) || !isUlid(value.run_id)) {
    return null
  }
  if (value.role === 'user') {
    if (
      typeof value.content !== 'string' ||
      !['queued', 'running', 'end_turn', 'cancelled', 'error', 'budget_exceeded'].includes(
        String(value.state),
      )
    ) {
      return null
    }
    return {
      message_id: value.message_id,
      run_id: value.run_id,
      role: 'user',
      content: value.content,
      state: value.state as UserMessageState,
    }
  }
  if (
    value.role !== 'assistant' ||
    value.message_id !== value.run_id ||
    typeof value.content !== 'string' ||
    typeof value.thinking !== 'string' ||
    !Array.isArray(value.events) ||
    !value.events.every(isJsonObject) ||
    typeof value.partial !== 'boolean'
  ) {
    return null
  }
  return {
    message_id: value.message_id,
    run_id: value.run_id,
    role: 'assistant',
    content: value.content,
    thinking: value.thinking,
    events: value.events,
    partial: value.partial,
  }
}

function parseSnapshot(value: unknown): ThreadSnapshotPayload | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value.messages) ||
    (value.resolved_model !== undefined &&
      (typeof value.resolved_model !== 'string' ||
        !value.resolved_model.trim()))
  ) {
    return null
  }
  const messages = value.messages.map(parseTranscriptMessage)
  if (messages.some((message) => message === null)) {
    return null
  }
  const openGate = value.open_gate === null ? null : parseGateOpen(value.open_gate)
  if (value.open_gate !== null && openGate === null) {
    return null
  }
  const activeRun = value.active_run === null ? null : parseActiveRun(value.active_run)
  if (value.active_run !== null && activeRun === null) {
    return null
  }
  return {
    messages: messages as TranscriptMessage[],
    open_gate: openGate,
    active_run: activeRun,
    resolved_model:
      typeof value.resolved_model === 'string' ? value.resolved_model : null,
  }
}

function parsePromptQueued(value: unknown): PromptQueuedPayload | null {
  if (!isRecord(value) || !isUlid(value.run_id) || !isUlid(value.prompt_id)) {
    return null
  }
  return { run_id: value.run_id, prompt_id: value.prompt_id }
}

function parseRunStarted(value: unknown): RunStartedPayload | null {
  const runIds = parsePromptQueued(value)
  if (
    runIds === null ||
    !isRecord(value) ||
    (value.resolved_model !== undefined &&
      (typeof value.resolved_model !== 'string' ||
        !value.resolved_model.trim()))
  ) {
    return null
  }
  return {
    ...runIds,
    resolved_model:
      typeof value.resolved_model === 'string' ? value.resolved_model : null,
  }
}

function parseRunDelta(value: unknown): RunDeltaPayload | null {
  if (!isRecord(value) || !isUlid(value.run_id)) {
    return null
  }
  if (
    (value.kind === 'text' || value.kind === 'thinking') &&
    typeof value.text === 'string'
  ) {
    return { run_id: value.run_id, kind: value.kind, text: value.text }
  }
  if (value.kind === 'event' && isJsonObject(value.event)) {
    return { run_id: value.run_id, kind: 'event', event: value.event }
  }
  return null
}

function parseRunUsage(value: unknown): RunUsagePayload | null {
  if (!isRecord(value) || !isUlid(value.run_id)) {
    return null
  }
  const usage = parseUsage(value)
  return usage === null ? null : { run_id: value.run_id, ...usage }
}

function parseRunDone(value: unknown): RunDonePayload | null {
  if (
    !isRecord(value) ||
    !isUlid(value.run_id) ||
    !['end_turn', 'cancelled', 'error', 'budget_exceeded'].includes(
      String(value.stop_reason),
    ) ||
    typeof value.partial !== 'boolean'
  ) {
    return null
  }
  const stopReason = value.stop_reason as StopReason
  if (value.partial !== (stopReason !== 'end_turn')) {
    return null
  }
  return {
    run_id: value.run_id,
    stop_reason: stopReason,
    partial: value.partial,
  }
}

export function decodeServerEnvelope(envelope: Envelope): DecodedServerEvent | null {
  let payload: unknown
  switch (envelope.type) {
    case 'thread.snapshot':
      payload = parseSnapshot(envelope.payload)
      return payload === null
        ? null
        : { type: 'thread.snapshot', payload: payload as ThreadSnapshotPayload }
    case 'run.started':
      payload = parseRunStarted(envelope.payload)
      return payload === null
        ? null
        : { type: 'run.started', payload: payload as RunStartedPayload }
    case 'prompt.queued':
      payload = parsePromptQueued(envelope.payload)
      return payload === null
        ? null
        : { type: 'prompt.queued', payload: payload as PromptQueuedPayload }
    case 'run.delta':
      payload = parseRunDelta(envelope.payload)
      return payload === null
        ? null
        : { type: 'run.delta', payload: payload as RunDeltaPayload }
    case 'run.usage':
      payload = parseRunUsage(envelope.payload)
      return payload === null
        ? null
        : { type: 'run.usage', payload: payload as RunUsagePayload }
    case 'run.done':
      payload = parseRunDone(envelope.payload)
      return payload === null
        ? null
        : { type: 'run.done', payload: payload as RunDonePayload }
    case 'gate.open':
      payload = parseGateOpen(envelope.payload)
      return payload === null
        ? null
        : { type: 'gate.open', payload: payload as GateOpenPayload }
    case 'gate.dismiss':
      if (!isRecord(envelope.payload) || !isUlid(envelope.payload.run_id)) {
        return null
      }
      return {
        type: 'gate.dismiss',
        payload: { run_id: envelope.payload.run_id },
      }
    case 'memory.panel.update':
      payload = parseMemoryPanelUpdate(envelope.payload)
      return payload === null
        ? null
        : {
            type: 'memory.panel.update',
            payload: payload as MemoryPanelServerPayload,
          }
    case 'error':
      return { type: 'error', payload: envelope.payload }
    default:
      return { type: 'unknown', payload: envelope.payload }
  }
}
