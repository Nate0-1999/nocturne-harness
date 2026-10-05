import type { JsonObject } from './protocol'
import { normalizedThreadTitle } from './threadTitles.ts'

export function elideBinaryPayload(key: string, value: unknown): unknown {
  if (value !== null && typeof value === 'object' && 'kind' in value &&
      value.kind === 'binary' && 'media_type' in value && 'data' in value &&
      typeof value.data === 'string') {
    const bytes = Math.floor(value.data.length * 3 / 4) - (value.data.match(/=+$/)?.[0].length ?? 0)
    return `… <${String(value.media_type)}, ${Math.ceil(bytes / 1024)} KB>`
  }
  if (key === 'data_base64' && typeof value === 'string') return '… <binary payload>'
  return value
}

export function browserScreenshotDataUrl(event: JsonObject): string | null {
  if (event.event_kind !== 'function_tool_result') return null
  const part = event.part
  if (part === null || Array.isArray(part) || typeof part !== 'object') return null
  if (part.tool_name !== 'screenshot' || !Array.isArray(event.content)) return null
  for (const value of event.content) {
    if (value === null || Array.isArray(value) || typeof value !== 'object') continue
    if (
      value.kind === 'binary' &&
      typeof value.media_type === 'string' &&
      value.media_type.startsWith('image/') &&
      typeof value.data === 'string'
    ) {
      // Pydantic emits URL-safe base64; data URLs require the standard alphabet.
      return `data:${value.media_type};base64,${value.data.replaceAll('-', '+').replaceAll('_', '/')}`
    }
  }
  return null
}

export interface ToolCallLine { id: string, tool: string, detail: string, outcome: string }

const OUTCOME_WORDS: Record<string, string> = { success: 'done', failed: 'failed', denied: 'refused' }

/** M3W6B-19: the tools drawer lists each call in plain words; the raw events stay one click deeper. */
export function toolCallLines(events: readonly JsonObject[]): ToolCallLine[] {
  const parts = events.flatMap((event) => {
    const part = event.part
    return part !== null && typeof part === 'object' && !Array.isArray(part) &&
      typeof part.tool_call_id === 'string' && typeof part.tool_name === 'string'
      ? [{ kind: event.event_kind, part }] : []
  })
  const outcomes = new Map(parts.filter(({ kind }) => kind === 'function_tool_result').map(({ part }) => [
    part.tool_call_id as string,
    String(part.content ?? '').startsWith(`${String(part.tool_name)} refused:`)
      ? 'refused'
      : OUTCOME_WORDS[String(part.outcome ?? 'success')] ?? String(part.outcome),
  ]))
  return parts.filter(({ kind }) => kind === 'function_tool_call').map(({ part }) => {
    let args: unknown = part.args
    if (typeof args === 'string') {
      try { args = JSON.parse(args) } catch { /* a model's unparsed arguments read as written */ }
    }
    const values = args !== null && typeof args === 'object'
      ? Object.values(args).filter((value) => ['string', 'number', 'boolean'].includes(typeof value)).map(String)
      : [String(args ?? '')]
    const detail = values.join(' · ').replace(/\s+/gu, ' ').trim()
    return {
      id: part.tool_call_id as string,
      tool: String(part.tool_name),
      detail: detail.length > 140 ? `${detail.slice(0, 139)}…` : detail,
      outcome: outcomes.get(part.tool_call_id as string) ?? 'no result yet',
    }
  })
}

export type RewindScope = 'conversation' | 'files' | 'both'

/** M3W6B-21/49: the line the conversation shows after a rewind, since the control leaves with its turn. */
export function rewindNotice(scope: RewindScope, prompt: string, commitsKept: readonly string[]): string {
  const what = scope === 'both' ? 'the chat and files' : scope === 'conversation' ? 'the chat' : 'the files'
  return [
    `Rewound ${what} to before “${normalizedThreadTitle(prompt)}”.`,
    scope === 'files' ? '' : 'Your prompt is back in the message box.',
    commitsKept.length === 0 ? '' : `Git commits made since then stay in the repository (${commitsKept.join('; ')}); undo them with git if you want them gone.`,
  ].filter(Boolean).join(' ')
}
