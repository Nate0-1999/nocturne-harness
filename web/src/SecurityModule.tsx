import { useEffect, useState } from 'react'

import type { JsonValue } from './protocol'
import { useRackPlugin, useRackSnapshot } from './rack'
import { formatHumanCount, formatHumanPercent } from './humanNumbers'
import './assets/security.css'

type Scope = 'GLOBAL' | 'ATTUNED'
interface Share { percent: number; limit_tokens: number; tokens: number }
interface Cut {
  thread_id: string; agent_id: string; at: string; kind: 'query' | 'sub_agent'; source: string
  size_tokens: number; share: Share; action: 'cut' | 'send_back'; shorten_by: number | null; attempt: number
}
interface Snapshot {
  bounds: { default_percent: number; min_percent: number; max_percent: number }
  shares: Record<string, Share>
  cuts: Cut[]
}

export function SecurityModule() {
  const { events, query } = useRackPlugin()
  const rack = useRackSnapshot()
  const [scope, setScope] = useState<Scope>('ATTUNED')
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [failed, setFailed] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'security' }).then(setScope)
  }, [events])

  useEffect(() => {
    let active = true
    const threadId = scope === 'ATTUNED' ? rack.selectedThreadId ?? undefined : undefined
    void query.query({ resource: 'overwhelm', as_of: 'now', thread_id: threadId })
      .then((result) => {
        if (!active) return
        setSnapshot(parseSnapshot(result.data))
        setFailed(false)
      })
      .catch(() => {
        if (!active) return
        setFailed(true)
      })
    return () => { active = false }
  }, [query, rack.selectedThreadId, refresh, scope])

  useEffect(() => events.subscribe((event) => {
    if (event.direction === 'inbound' && event.envelope.type === 'run.done') {
      setRefresh((value) => value + 1)
    }
  }), [events])

  const threadShare = rack.selectedThreadId ? snapshot?.shares[rack.selectedThreadId] ?? null : null
  const share = threadShare ?? Object.values(snapshot?.shares ?? {}).at(-1) ?? null
  const cuts = snapshot?.cuts.slice().reverse() ?? []
  const sendBacks = cuts.filter((cut) => cut.action === 'send_back').length

  return (
    <section className="security-instrument" aria-label="Context shares">
      <header>
        <h1>Security</h1>
        {snapshot && (
          <dl className="security-shares" data-testid="security-shares">
            <div>
              <dt>Share</dt>
              <dd title="One query or sub-agent return may take this much of the compaction limit">
                {share
                  ? `${formatHumanPercent(share.percent)} · ${formatHumanCount(share.tokens)} of ${formatHumanCount(share.limit_tokens)}`
                  : `${formatHumanPercent(snapshot.bounds.default_percent)} default`}
              </dd>
            </div>
            <div>
              <dt>Bounds</dt>
              <dd title="A sender may pick a share inside these system bounds">
                {formatHumanPercent(snapshot.bounds.min_percent)} – {formatHumanPercent(snapshot.bounds.max_percent)}
              </dd>
            </div>
            <div><dt>Cuts</dt><dd>{cuts.length - sendBacks}</dd></div>
            <div><dt>Send-backs</dt><dd>{sendBacks}</dd></div>
          </dl>
        )}
      </header>
      {failed && <p role="alert">Context shares unavailable</p>}
      {snapshot && (
        <div className="security-scroll">
          <table data-testid="security-cuts">
            <thead><tr><th>When</th><th>Kind</th><th>Source</th><th>Size</th><th>Share</th><th>Action</th></tr></thead>
            <tbody>
              {cuts.length === 0
                ? <tr><td colSpan={6} className="security-empty">No cuts</td></tr>
                : cuts.map((cut, index) => (
                  <tr key={index} data-action={cut.action}>
                    <td>{new Date(cut.at).toLocaleTimeString()}</td>
                    <td>{cut.kind === 'query' ? 'Query' : 'Sub-agent'}</td>
                    <td title={cut.agent_id}>{cut.source}</td>
                    <td>{formatHumanCount(cut.size_tokens)}</td>
                    <td>{formatHumanCount(cut.share.tokens)} · {formatHumanPercent(cut.share.percent)}</td>
                    <td>
                      {cut.action === 'cut'
                        ? 'Cut · head delivered'
                        : `Sent back ×${cut.attempt} · shorten by ${formatHumanCount(cut.shorten_by ?? 0)}`}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function parseSnapshot(value: JsonValue | null): Snapshot | null {
  if (!isRecord(value) || !isRecord(value.bounds) || !isRecord(value.shares) || !Array.isArray(value.cuts)) return null
  return value as unknown as Snapshot
}

function isRecord(value: unknown): value is Record<string, JsonValue> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
