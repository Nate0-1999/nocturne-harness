import { useEffect, useState } from 'react'
import { Button, TextField } from './kit'

export function SpendWallSettings() {
  const [run, setRun] = useState('')
  const [day, setDay] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [status, setStatus] = useState('Reading spend walls…')
  useEffect(() => {
    fetch('/v1/spend-walls').then(async (response) => {
      if (!response.ok) throw new Error('Spend walls unavailable')
      const value = await response.json()
      setRun(value.run_usd ?? '')
      setDay(value.day_usd ?? '')
      setLoaded(true)
      setStatus('Blank means no limit. Daily spend resets at midnight UTC.')
    }).catch((error: Error) => setStatus(error.message))
  }, [])
  async function save() {
    try {
      const response = await fetch('/v1/spend-walls', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_usd: run || null, day_usd: day || null }),
      })
      if (!response.ok) throw new Error('Enter positive dollar limits, or leave blank.')
      setStatus('Spend walls saved. Paused runs recheck these limits.')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Spend walls unavailable') }
  }
  return <section className="agent-policy-settings">
    <h2>Spend walls</h2>
    <form onSubmit={(event) => { event.preventDefault(); void save() }}>
      <label>Per run · USD<TextField aria-label="Per-run spend wall USD" data-tooltip-detail="Pause a run when its reported spend reaches this. A request already underway can finish past it." type="number" min="0.000001" step="any" value={run} disabled={!loaded} onChange={(event) => setRun(event.target.value)} /></label>
      <label>Per UTC day · USD<TextField aria-label="Daily spend wall USD" data-tooltip-detail="Pause ordinary runs when the day's reported spend reaches this." type="number" min="0.000001" step="any" value={day} disabled={!loaded} onChange={(event) => setDay(event.target.value)} /></label>
      <Button variant="primary" data-tooltip-detail="Save both limits; paused runs recheck them." disabled={!loaded} type="submit">Save spend walls</Button>
    </form>
    <p role="status">{status}</p>
  </section>
}
