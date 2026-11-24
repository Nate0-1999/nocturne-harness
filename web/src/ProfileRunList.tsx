import { Button } from './kit'
import type { RunningProfile } from './store'

export function ProfileRunList({ runs, current, opened, onOpen }: {
  runs: RunningProfile[]; current: string | null; opened?: string; onOpen: (id: string) => void
}) {
  if (!runs.length) return null
  const ordered = [...runs].sort((a, b) => Number(b.thread_id === current) - Number(a.thread_id === current))
  return <nav className="profiler-live-runs" aria-label="Running profiles">
    <strong>Running</strong>
    {ordered.map((run) => <Button key={run.run_id} type="button"
      data-testid="open-running-profile" data-run-id={run.run_id} aria-pressed={opened ? run.run_id === opened : undefined}
      title={`Show bars for ${run.name}`} onClick={() => onOpen(run.run_id)}><span>{run.name}</span></Button>)}
  </nav>
}
