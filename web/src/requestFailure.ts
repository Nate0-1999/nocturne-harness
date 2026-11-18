/** Messages cross the request boundary deliberately; caught exception text never does. */
export class RequestFailure extends Error {
  readonly publicMessage: string | null
  constructor(publicMessage: string | null) {
    super(publicMessage ?? 'The request could not finish. Try again.')
    this.publicMessage = publicMessage
  }
}

// These are the Palace/Harness API's authored messages, not exception strings. New API
// copy belongs here too until the protocol distinguishes public copy from diagnostics.
const PUBLIC_MESSAGES = new Set([
  'A curator pass is already running for this Palace.',
  'Checking the bill needs a newer Palace.',
  'Choose a recorded time with a timezone.',
  'Choose a thread to see its tools.',
  'Cloud Palace restore is a human Cloud SQL operation.',
  'Commit or save this folder\'s changes before signing a Symphony.',
  'Context shares are unavailable.',
  'Context usage is unavailable.',
  'Detailed spend is unavailable. Try again.',
  'Detailed spend needs a newer Palace.',
  'History compacted; the Palace could not start optimization.',
  'Injection controls are unavailable.',
  'Injection simulation is unavailable.',
  'Jobs need an updated, reachable Palace.',
  'Memory did not confirm the requested change. Refresh and try again.',
  'Memory is unavailable; continuing without injected context.',
  'Memory instrumentation is unavailable.',
  'Memory scoring unavailable',
  'The memory service is unavailable. Try again.',
  'The memory service rejected this request. Refresh and try again.',
  'The memory service returned an invalid response.',
  'The memory request failed. Try again.',
  'No recorded visualization state at this time.',
  'Nothing changed. Edit the memory body before saving.',
  'Only the Palace owner can configure curator models.',
  'Only the Palace owner can reconcile spend.',
  'Only the Palace owner can record infrastructure invoices.',
  'Only the Palace owner can retrain the scorer.',
  'Only the Palace owner can view the whole Palace.',
  'Palace Vitals are unavailable.',
  'Proof failed. The previous proven release stays enabled.',
  'Retrain job not found.',
  'Retrain status is unavailable.',
  'Retraining could not be started.',
  'Run is absent or already finished.',
  'Scorer audition is unavailable.',
  'Scorer retraining is unavailable.',
  'Symphony stack was not found.',
  'That card is already gone.',
  'The Palace could not save the curator policy.',
  'The embedding provider could not complete the request.',
  'The live recipe is unavailable.',
  'The memory service rejected this change because of a conflict.',
  'The model\'s final answer did not match the answer it streamed.',
  'The Palace is busy. Try again.',
  'The Palace is busy, retrying.',
  'The Palace is ready.',
  'The Palace is still busy. Try again shortly.',
  'The parameter registry is unavailable.',
  'The scheduled occurrence changed.',
  'The turn received invalid data. See the daemon log for details.',
  'The workflow changed. Refresh before saving.',
  'This Palace has no OpenRouter key to reconcile against.',
  'This invoice ID already has a different amount or date.',
  'This job is not running here.',
  'This memory changed while you were editing it. Review the latest version and try again.',
  'This memory is not deleted. Refresh and try again.',
  'This active memory is no longer available. Refresh and try again.',
  'This attempt has already returned; the judges are reviewing it.',
  'This occurrence was already started.',
  'This schedule is not due.',
  'This schedule is paused.',
  'Thread Vitals are unavailable.',
  'Thread image journal is unavailable.',
  'Thread image was not found.',
  'Tie target does not match its source.',
  'Tie winner is not one of the tied sources.',
  'Worker context is not available.',
  'Workflow is already running or changed. Refresh it.',
  'Workflow not found.',
])

/** The same detail field can contain a sentence, JSON, a code, or str(exception). */
export function publicMessage(value: unknown): string | null {
  if (typeof value !== 'string') return null
  if (PUBLIC_MESSAGES.has(value)) return value
  if (/^This thread already belongs to (?:project [^\n]+|unscoped history)\. Start a new thread in project [^\n]+\.$/.test(value)) return value
  // F230: with the Palace down this notice follows the local-copy one in the same run.
  if (/^Answer delivered; \d+ spend receipt line\(s\) are waiting for the ledger \((?:durably on disk|in degraded memory)\)\.$/.test(value)) return value
  // The local-copy notice has a human clock time; keepMemoryNotice can join it to a
  // second authored notice. Neither path is an arbitrary exception-message escape.
  const localCopy = /^(?:The Palace is unreachable; memory|The Palace did not answer in time; memory|Memory) is from the local copy, as of (?:\d{2}:\d{2}|[A-Z][a-z]{2} \d{1,2}, \d{2}:\d{2}|an unknown time)\./.exec(value)?.[0]
  for (const message of localCopy ? [...PUBLIC_MESSAGES, localCopy] : PUBLIC_MESSAGES) {
    if (value === message || (value.startsWith(`${message} `) && publicMessage(value.slice(message.length + 1)))) return value
  }
  return null
}

export function failureMessage(error: unknown, next: string): string {
  const message = error instanceof RequestFailure ? error.publicMessage : null
  if (message === null) return next
  if (/\b(?:Choose|Commit|Save|Edit|Refresh|Try|Start|Keep|Open|Finish|Reload|Ask|Wait|Check)\b/i.test(message)) return message
  const recovery = message.startsWith('Only the Palace owner') ? 'Ask the Palace owner to do this.'
    : message.includes('newer Palace') || message.includes('updated, reachable Palace') ? 'Update your Palace and reload.'
    : message.startsWith('Cloud Palace restore') ? 'Ask your Palace operator to restore the backup.'
    : 'Try again.'
  return `${message} ${recovery}`
}

export async function responseFailure(response: Response): Promise<RequestFailure> {
  if (response.status === 429) return new RequestFailure('The Palace is busy. Try again.')
  const body = await response.json().catch(() => null) as { detail?: unknown } | null
  return new RequestFailure(publicMessage(body?.detail))
}

export function serverMessage(value: unknown, next: string): string {
  return publicMessage(value) ?? next
}
