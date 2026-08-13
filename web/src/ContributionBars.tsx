const FEATURES = ['sem', 'kw', 'time', 'proj', 'freq', 'hist', 'bias'] as const

export function ContributionBars({ values }: { values?: Record<string, string> | null }) {
  if (values == null) return <p className="contribution-empty">Not scored yet.</p>
  const maximum = Math.max(...FEATURES.map((key) => Math.abs(Number(values[key] ?? 0))), 0.001)
  return (
    <div className="contribution-bars" aria-label="Weighted score contributions">
      {FEATURES.map((key) => {
        const value = Number(values[key] ?? 0)
        return <div className="contribution-row" key={key}>
          <span>{key}</span>
          <i><b style={{ width: `${Math.abs(value) / maximum * 100}%` }} data-negative={value < 0 || undefined} /></i>
          <output>{formatHumanScore(values[key] ?? 0)}</output>
        </div>
      })}
    </div>
  )
}

// eslint-disable-next-line react-refresh/only-export-components -- paired rack instrumentation hook
export function useContributionMap(): Record<string, Record<string, string>> {
  const { query } = useRackPlugin(); const rack = useRackSnapshot()
  const [values, setValues] = useState<Record<string, Record<string, string>>>({})
  useEffect(() => {
    if (rack.selectedThreadId === null) {
      queueMicrotask(() => setValues({}))
      return
    }
    void query.query({ resource: 'scorer_console', as_of: 'now', thread_id: rack.selectedThreadId })
      .then((result) => {
        const data = result.data as unknown as { candidates?: { memory_id: string; points: { contributions: Record<string, string> }[] }[] }
        setValues(Object.fromEntries((data.candidates ?? []).flatMap((candidate) => {
          const point = candidate.points.at(-1); return point === undefined ? [] : [[candidate.memory_id, point.contributions]]
        })))
      }).catch(() => setValues({}))
  }, [query, rack.selectedThreadId])
  return values
}

export interface ScorerPreviewMark {
  preview_score: string
  preview_rank: number
  disposition: 'also_shown' | 'would_add' | 'would_drop' | 'still_out'
}

// eslint-disable-next-line react-refresh/only-export-components -- paired presentation hook
export function useScorerAuditionMap(): Record<string, ScorerPreviewMark> {
  const [values, setValues] = useState<Record<string, ScorerPreviewMark>>({})
  useEffect(() => {
    const receive = (event: Event) => {
      const detail = (event as CustomEvent).detail as { instant?: { candidates?: ({ memory_id: string } & ScorerPreviewMark)[] } }
      setValues(Object.fromEntries((detail.instant?.candidates ?? []).map((row)=>[row.memory_id,row])))
    }
    globalThis.addEventListener('nocturne:scorer-audition', receive)
    return () => globalThis.removeEventListener('nocturne:scorer-audition', receive)
  }, [])
  return values
}
import { useEffect, useState } from 'react'
import { formatHumanScore } from './humanNumbers.ts'
import { useRackPlugin, useRackSnapshot } from './rack'
