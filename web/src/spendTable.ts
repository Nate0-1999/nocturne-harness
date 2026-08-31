export interface SpendMetrics {
  input_tokens: string
  kv_cache_tokens: string
  reasoning_tokens: string
  output_tokens: string
  total_usd: string | null
  total_receipt_lines: number
  total_unpriced_lines: number
  spend_per_hour_usd: string | null
  hourly_receipt_lines: number
  hourly_unpriced_lines: number
}

export interface ModelSpendRow extends SpendMetrics {
  model: string | null
}

export interface ThreadSpendRow extends SpendMetrics {
  thread_id: string
  models: ModelSpendRow[]
}

export interface PurposeSpendRow extends SpendMetrics {
  purpose: string
  label: string
}

export interface SpendTableSnapshot {
  as_of: string
  window_minutes: 60
  threads: ThreadSpendRow[]
  purposes: PurposeSpendRow[]
}

const DECIMAL = /^(?:0|[1-9]\d*)(?:\.\d+)?$/
const OFFSET_TIMESTAMP = /(?:Z|[+-]\d{2}:\d{2})$/

/** PLAN M3SP / ADR-024 keeps the browser a strict reader of one server-authored ledger projection. */
export function parseSpendTableSnapshot(value: unknown): SpendTableSnapshot {
  const root = record(value, 'Spend table')
  if (root.window_minutes !== 60) {
    throw new TypeError('Spend table window must be 60 minutes')
  }
  if (!Array.isArray(root.threads) || !Array.isArray(root.purposes)) {
    throw new TypeError('Spend table rows must be arrays')
  }
  const threads = root.threads.map(parseThreadRow)
  const purposes = root.purposes.map(parsePurposeRow)
  unique(threads.map((row) => row.thread_id), 'thread')
  unique(purposes.map((row) => row.purpose), 'purpose')
  return {
    as_of: timestamp(root.as_of, 'as_of'),
    window_minutes: 60,
    threads,
    purposes,
  }
}

export function partialSpendCopy(row: SpendMetrics): string | null {
  const lines = row.total_unpriced_lines || row.hourly_unpriced_lines
  return lines === 0 ? null : `${lines} ${lines === 1 ? 'line' : 'lines'} awaiting a price`
}

function parseThreadRow(value: unknown, index: number): ThreadSpendRow {
  const row = record(value, `threads[${index}]`)
  if (typeof row.thread_id !== 'string' || row.thread_id.length === 0) {
    throw new TypeError(`threads[${index}].thread_id must be nonblank`)
  }
  if (!Array.isArray(row.models)) {
    throw new TypeError(`threads[${index}].models must be an array`)
  }
  const models = row.models.map(parseModelRow)
  unique(models.map((model) => model.model ?? '\u0000'), `threads[${index}] model`)
  return { thread_id: row.thread_id, models, ...parseMetrics(row, `threads[${index}]`) }
}

function parseModelRow(value: unknown, index: number): ModelSpendRow {
  const row = record(value, `models[${index}]`)
  if (row.model !== null && (typeof row.model !== 'string' || row.model.length === 0)) {
    throw new TypeError(`models[${index}].model must be nonblank or null`)
  }
  return { model: row.model as string | null, ...parseMetrics(row, `models[${index}]`) }
}

function parsePurposeRow(value: unknown, index: number): PurposeSpendRow {
  const row = record(value, `purposes[${index}]`)
  if (typeof row.purpose !== 'string' || row.purpose.length === 0) {
    throw new TypeError(`purposes[${index}].purpose must be nonblank`)
  }
  if (typeof row.label !== 'string' || row.label.trim().length === 0) {
    throw new TypeError(`purposes[${index}].label must be human-readable`)
  }
  return {
    purpose: row.purpose,
    label: row.label,
    ...parseMetrics(row, `purposes[${index}]`),
  }
}

function parseMetrics(row: Record<string, unknown>, path: string): SpendMetrics {
  const totalReceiptLines = integer(row.total_receipt_lines, `${path}.total_receipt_lines`)
  const totalUnpricedLines = integer(row.total_unpriced_lines, `${path}.total_unpriced_lines`)
  const hourlyReceiptLines = integer(row.hourly_receipt_lines, `${path}.hourly_receipt_lines`)
  const hourlyUnpricedLines = integer(row.hourly_unpriced_lines, `${path}.hourly_unpriced_lines`)
  if (totalUnpricedLines > totalReceiptLines || hourlyUnpricedLines > hourlyReceiptLines) {
    throw new TypeError(`${path} has impossible unpriced receipt counts`)
  }
  return {
    input_tokens: decimal(row.input_tokens, `${path}.input_tokens`),
    kv_cache_tokens: decimal(row.kv_cache_tokens, `${path}.kv_cache_tokens`),
    reasoning_tokens: decimal(row.reasoning_tokens, `${path}.reasoning_tokens`),
    output_tokens: decimal(row.output_tokens, `${path}.output_tokens`),
    total_usd: nullableCost(row.total_usd, totalReceiptLines, totalUnpricedLines, `${path}.total_usd`),
    total_receipt_lines: totalReceiptLines,
    total_unpriced_lines: totalUnpricedLines,
    spend_per_hour_usd: nullableCost(
      row.spend_per_hour_usd,
      hourlyReceiptLines,
      hourlyUnpricedLines,
      `${path}.spend_per_hour_usd`,
    ),
    hourly_receipt_lines: hourlyReceiptLines,
    hourly_unpriced_lines: hourlyUnpricedLines,
  }
}

function nullableCost(
  value: unknown,
  receiptLines: number,
  unpricedLines: number,
  path: string,
): string | null {
  if (value === null) {
    if (receiptLines !== unpricedLines && receiptLines > 0) {
      throw new TypeError(`${path} omits a known price`)
    }
    return null
  }
  const parsed = decimal(value, path)
  if (receiptLines === unpricedLines && receiptLines > 0) {
    throw new TypeError(`${path} prices an all-unpriced row`)
  }
  return parsed
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`${path} must be an object`)
  }
  return value as Record<string, unknown>
}

function decimal(value: unknown, path: string): string {
  if (typeof value !== 'string' || !DECIMAL.test(value)) {
    throw new TypeError(`${path} must be an exact non-negative decimal string`)
  }
  return value
}

function integer(value: unknown, path: string): number {
  if (!Number.isInteger(value) || Number(value) < 0) {
    throw new TypeError(`${path} must be a non-negative integer`)
  }
  return Number(value)
}

function timestamp(value: unknown, path: string): string {
  if (typeof value !== 'string' || !OFFSET_TIMESTAMP.test(value) || !Number.isFinite(Date.parse(value))) {
    throw new TypeError(`${path} must be an offset-aware timestamp`)
  }
  return value
}

function unique(values: string[], label: string): void {
  if (new Set(values).size !== values.length) {
    throw new TypeError(`Spend table ${label} rows must be unique`)
  }
}
