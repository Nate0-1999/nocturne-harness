export type SpendLaneDimension = 'total' | 'purpose' | 'model'
export type GaugeStatus = 'measured' | 'not_recorded' | 'placeholder'

export interface SpendPoint {
  minute: string
  cost_usd: string | null
  receipt_lines: number
  unpriced_lines: number
}

export interface SpendLane {
  dimension: SpendLaneDimension
  key: string | null
  label: string
  points: SpendPoint[]
}

export interface LifecycleRate {
  metric: string
  status: GaugeStatus
  per_hour: number | null
  source: string | null
}

export interface PalaceCount {
  metric: string
  status: GaugeStatus
  count: number | null
  source: string | null
}

export type ReconciliationStatus = 'not_recorded' | 'baseline' | 'balanced' | 'drift' | 'unavailable'

export interface ReconciliationSnapshot {
  status: ReconciliationStatus
  checked_at: string | null
  broker_usage_usd: string | null
  ledger_cost_usd: string | null
  broker_since_baseline_usd: string | null
  ledger_since_baseline_usd: string | null
  drift_usd: string | null
  tolerance_usd: string | null
  unpriced_lines: number
  source: 'openrouter:/api/v1/key' | null
  error_code: 'broker_unavailable' | 'invalid_broker_response' | null
}

export interface VitalsSnapshot {
  as_of: string
  window_minutes: 60
  spend: {
    source_view: 'v_spend_rate'
    latest_minute: string | null
    lanes: SpendLane[]
  }
  reconciliation: ReconciliationSnapshot
  lifecycle_rates: LifecycleRate[]
  palace_counts: PalaceCount[]
}

export interface LaneChartPoint {
  point: SpendPoint
  x: number
  y: number | null
}

const DECIMAL = /^(?:0|[1-9]\d*)(?:\.\d+)?$/
const SIGNED_DECIMAL = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/
const OFFSET_TIMESTAMP = /(?:Z|[+-]\d{2}:\d{2})$/

export function parseVitalsSnapshot(value: unknown): VitalsSnapshot {
  const root = record(value, 'Vitals response')
  const asOf = timestamp(root.as_of, 'as_of')
  if (root.window_minutes !== 60) {
    throw new TypeError('Vitals window must be the live trailing 60 minutes')
  }

  const spend = record(root.spend, 'spend')
  if (spend.source_view !== 'v_spend_rate') {
    throw new TypeError('Vitals spend must come from v_spend_rate')
  }
  const latestMinute = spend.latest_minute === null
    ? null
    : timestamp(spend.latest_minute, 'spend.latest_minute')
  if (!Array.isArray(spend.lanes)) {
    throw new TypeError('Vitals spend lanes must be an array')
  }

  return {
    as_of: asOf,
    window_minutes: 60,
    spend: {
      source_view: 'v_spend_rate',
      latest_minute: latestMinute,
      lanes: spend.lanes.map(parseSpendLane),
    },
    reconciliation: parseReconciliation(root.reconciliation),
    lifecycle_rates: gaugeArray(root.lifecycle_rates, parseLifecycleRate, 'lifecycle_rates'),
    palace_counts: gaugeArray(root.palace_counts, parsePalaceCount, 'palace_counts'),
  }
}

export function spendLaneId(lane: SpendLane): string {
  return lane.dimension === 'total' ? 'total' : `${lane.dimension}:${lane.key}`
}

export function formatExactUsd(value: string | null): string {
  if (value === null) {
    return 'Awaiting price'
  }
  if (!DECIMAL.test(value)) {
    throw new TypeError('Cost must be an exact non-negative decimal string')
  }
  const [whole, fraction] = value.split('.')
  const groupedWhole = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `$${groupedWhole}${fraction === undefined ? '' : `.${fraction}`}`
}

export function reconciliationCopy(value: ReconciliationSnapshot): string {
  switch (value.status) {
    case 'baseline': return 'Ledger audit · Baseline set'
    case 'balanced': return 'Ledger audit · Aligned'
    case 'drift': return `Ledger drift · ${formatSignedUsd(value.drift_usd)}`
    case 'unavailable': return 'Ledger audit · Temporarily unavailable'
    case 'not_recorded': return 'Ledger audit · Not recorded'
  }
}

export function formatSignedUsd(value: string | null): string {
  if (value === null || !SIGNED_DECIMAL.test(value)) {
    throw new TypeError('Drift must be an exact signed decimal string')
  }
  const sign = value.startsWith('-') ? '-' : '+'
  return `${sign}${formatExactUsd(value.replace(/^-/, ''))}`
}

export function unpricedCopy(count: number): string | null {
  if (count === 0) {
    return null
  }
  return `${count} ${count === 1 ? 'line' : 'lines'} awaiting a price`
}

export function latestSpendPoint(lane: SpendLane): SpendPoint | null {
  return lane.points[lane.points.length - 1] ?? null
}

export function nearestSpendPoint(
  points: readonly SpendPoint[],
  asOf: string,
  position: number,
  windowMinutes = 60,
): SpendPoint | null {
  if (points.length === 0) {
    return null
  }
  const end = Date.parse(asOf)
  const start = end - windowMinutes * 60_000
  const target = start + clamp(position, 0, 1) * (end - start)
  return points.reduce((nearest, candidate) => {
    const nearestDistance = Math.abs(Date.parse(nearest.minute) - target)
    const candidateDistance = Math.abs(Date.parse(candidate.minute) - target)
    return candidateDistance < nearestDistance ? candidate : nearest
  })
}

export function laneChartPoints(
  lane: SpendLane,
  asOf: string,
  windowMinutes = 60,
): LaneChartPoint[] {
  const end = Date.parse(asOf)
  const start = end - windowMinutes * 60_000
  const priced = lane.points
    .map((point) => point.cost_usd === null ? null : Number(point.cost_usd))
    .filter((value): value is number => value !== null && Number.isFinite(value))
  const maximum = Math.max(...priced, 0)
  return lane.points.map((point) => {
    const x = clamp(((Date.parse(point.minute) - start) / (end - start)) * 100, 0, 100)
    const numericCost = point.cost_usd === null ? null : Number(point.cost_usd)
    const y = numericCost === null || !Number.isFinite(numericCost)
      ? null
      : maximum === 0
        ? 18
        : 21 - (numericCost / maximum) * 17
    return { point, x, y }
  })
}

export function contiguousPolylineSegments(
  points: readonly LaneChartPoint[],
  maximumGapMilliseconds = 60_000,
): string[] {
  const segments: string[] = []
  let current: string[] = []
  let previousMinute: number | null = null
  for (const point of points) {
    const minute = Date.parse(point.point.minute)
    if (
      point.y === null ||
      (previousMinute !== null && minute - previousMinute > maximumGapMilliseconds)
    ) {
      if (current.length > 0) {
        segments.push(current.join(' '))
      }
      current = []
    }
    if (point.y === null) {
      previousMinute = null
      continue
    }
    current.push(`${point.x},${point.y}`)
    previousMinute = minute
  }
  if (current.length > 0) {
    segments.push(current.join(' '))
  }
  return segments
}

function parseSpendLane(value: unknown, index: number): SpendLane {
  const lane = record(value, `spend.lanes[${index}]`)
  if (lane.dimension !== 'total' && lane.dimension !== 'purpose' && lane.dimension !== 'model') {
    throw new TypeError(`spend.lanes[${index}].dimension is invalid`)
  }
  const key = lane.key
  if (lane.dimension === 'total') {
    if (key !== null) {
      throw new TypeError('The total spend lane must have a null key')
    }
  } else if (typeof key !== 'string' || key.length === 0) {
    throw new TypeError(`${lane.dimension} spend lanes require a stable key`)
  }
  if (typeof lane.label !== 'string' || lane.label.trim().length === 0) {
    throw new TypeError(`spend.lanes[${index}].label must be human-readable`)
  }
  if (!Array.isArray(lane.points)) {
    throw new TypeError(`spend.lanes[${index}].points must be an array`)
  }
  return {
    dimension: lane.dimension,
    key: key as string | null,
    label: lane.label,
    points: lane.points.map((point, pointIndex) => parseSpendPoint(point, index, pointIndex)),
  }
}

function parseReconciliation(value: unknown): ReconciliationSnapshot {
  const item = record(value, 'reconciliation')
  const statuses: ReconciliationStatus[] = [
    'not_recorded', 'baseline', 'balanced', 'drift', 'unavailable',
  ]
  if (!statuses.includes(item.status as ReconciliationStatus)) {
    throw new TypeError('reconciliation.status is invalid')
  }
  const decimal = (field: string, signed = false): string | null => {
    const candidate = item[field]
    if (candidate === null) return null
    if (typeof candidate !== 'string' || !(signed ? SIGNED_DECIMAL : DECIMAL).test(candidate)) {
      throw new TypeError(`reconciliation.${field} must be an exact decimal string or null`)
    }
    return candidate
  }
  const checkedAt = item.checked_at === null
    ? null
    : timestamp(item.checked_at, 'reconciliation.checked_at')
  if (item.source !== null && item.source !== 'openrouter:/api/v1/key') {
    throw new TypeError('reconciliation.source is invalid')
  }
  if (
    item.error_code !== null &&
    item.error_code !== 'broker_unavailable' &&
    item.error_code !== 'invalid_broker_response'
  ) {
    throw new TypeError('reconciliation.error_code is invalid')
  }
  const result: ReconciliationSnapshot = {
    status: item.status as ReconciliationStatus,
    checked_at: checkedAt,
    broker_usage_usd: decimal('broker_usage_usd'),
    ledger_cost_usd: decimal('ledger_cost_usd'),
    broker_since_baseline_usd: decimal('broker_since_baseline_usd'),
    ledger_since_baseline_usd: decimal('ledger_since_baseline_usd'),
    drift_usd: decimal('drift_usd', true),
    tolerance_usd: decimal('tolerance_usd'),
    unpriced_lines: nonnegativeInteger(item.unpriced_lines, 'reconciliation.unpriced_lines'),
    source: item.source as 'openrouter:/api/v1/key' | null,
    error_code: item.error_code as 'broker_unavailable' | 'invalid_broker_response' | null,
  }
  const observations = [
    result.broker_usage_usd,
    result.ledger_cost_usd,
    result.broker_since_baseline_usd,
    result.ledger_since_baseline_usd,
    result.drift_usd,
  ]
  if (result.status === 'not_recorded') {
    if (
      result.checked_at !== null || observations.some((entry) => entry !== null) ||
      result.tolerance_usd !== null || result.error_code !== null
    ) {
      throw new TypeError('not_recorded reconciliation cannot contain a result')
    }
  } else if (result.status === 'unavailable') {
    if (
      result.checked_at === null || observations.some((entry) => entry !== null) ||
      result.tolerance_usd === null || result.error_code === null || result.source === null
    ) {
      throw new TypeError('unavailable reconciliation has an invalid shape')
    }
  } else if (
    result.checked_at === null || observations.some((entry) => entry === null) ||
    result.tolerance_usd === null || result.error_code !== null || result.source === null
  ) {
    throw new TypeError('successful reconciliation has an invalid shape')
  }
  return result
}

function parseSpendPoint(value: unknown, laneIndex: number, pointIndex: number): SpendPoint {
  const prefix = `spend.lanes[${laneIndex}].points[${pointIndex}]`
  const point = record(value, prefix)
  const cost = point.cost_usd
  if (cost !== null && (typeof cost !== 'string' || !DECIMAL.test(cost))) {
    throw new TypeError(`${prefix}.cost_usd must be an exact decimal string or null`)
  }
  return {
    minute: timestamp(point.minute, `${prefix}.minute`),
    cost_usd: cost as string | null,
    receipt_lines: nonnegativeInteger(point.receipt_lines, `${prefix}.receipt_lines`),
    unpriced_lines: nonnegativeInteger(point.unpriced_lines, `${prefix}.unpriced_lines`),
  }
}

function parseLifecycleRate(value: unknown, index: number): LifecycleRate {
  const gauge = record(value, `lifecycle_rates[${index}]`)
  const status = gaugeStatus(gauge.status, `lifecycle_rates[${index}].status`)
  const perHour = nullableNonnegativeNumber(gauge.per_hour, `lifecycle_rates[${index}].per_hour`)
  const source = nullableSource(gauge.source, `lifecycle_rates[${index}].source`)
  enforceGaugeHonesty(status, perHour, source, `lifecycle_rates[${index}]`)
  return { metric: metric(gauge.metric, `lifecycle_rates[${index}].metric`), status, per_hour: perHour, source }
}

function parsePalaceCount(value: unknown, index: number): PalaceCount {
  const gauge = record(value, `palace_counts[${index}]`)
  const status = gaugeStatus(gauge.status, `palace_counts[${index}].status`)
  const count = gauge.count === null
    ? null
    : nonnegativeInteger(gauge.count, `palace_counts[${index}].count`)
  const source = nullableSource(gauge.source, `palace_counts[${index}].source`)
  enforceGaugeHonesty(status, count, source, `palace_counts[${index}]`)
  return { metric: metric(gauge.metric, `palace_counts[${index}].metric`), status, count, source }
}

function gaugeArray<T>(
  value: unknown,
  parser: (entry: unknown, index: number) => T,
  name: string,
): T[] {
  if (!Array.isArray(value)) {
    throw new TypeError(`${name} must be an array`)
  }
  return value.map(parser)
}

function enforceGaugeHonesty(
  status: GaugeStatus,
  numericValue: number | null,
  source: string | null,
  name: string,
): void {
  if (status === 'measured') {
    if (numericValue === null || source === null) {
      throw new TypeError(`${name} measured gauges require a value and source`)
    }
    return
  }
  if (numericValue !== null || source !== null) {
    throw new TypeError(`${name} unavailable gauges must not masquerade as zero`)
  }
}

function gaugeStatus(value: unknown, name: string): GaugeStatus {
  if (value !== 'measured' && value !== 'not_recorded' && value !== 'placeholder') {
    throw new TypeError(`${name} is invalid`)
  }
  return value
}

function metric(value: unknown, name: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new TypeError(`${name} must be a non-empty string`)
  }
  return value
}

function nullableSource(value: unknown, name: string): string | null {
  if (value === null) {
    return null
  }
  if (typeof value !== 'string' || value.length === 0) {
    throw new TypeError(`${name} must be a non-empty string or null`)
  }
  return value
}

function nullableNonnegativeNumber(value: unknown, name: string): number | null {
  if (value === null) {
    return null
  }
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    throw new TypeError(`${name} must be a non-negative number or null`)
  }
  return value
}

function nonnegativeInteger(value: unknown, name: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new TypeError(`${name} must be a non-negative integer`)
  }
  return value
}

function timestamp(value: unknown, name: string): string {
  if (
    typeof value !== 'string' ||
    !OFFSET_TIMESTAMP.test(value) ||
    !Number.isFinite(Date.parse(value))
  ) {
    throw new TypeError(`${name} must be an offset-aware timestamp`)
  }
  return value
}

function record(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`)
  }
  return value as Record<string, unknown>
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value))
}
