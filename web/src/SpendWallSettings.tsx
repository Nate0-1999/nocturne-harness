import { useEffect, useState } from 'react'

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
    <p>Pause ordinary runs when reported spend reaches either limit. A request already underway can cross the limit before its price arrives.</p>
    <form onSubmit={(event) => { event.preventDefault(); void save() }}>
      <label>Per run · USD<input aria-label="Per-run spend wall USD" type="number" min="0.000001" step="any" value={run} disabled={!loaded} onChange={(event) => setRun(event.target.value)} /></label>
      <label>Per UTC day · USD<input aria-label="Daily spend wall USD" type="number" min="0.000001" step="any" value={day} disabled={!loaded} onChange={(event) => setDay(event.target.value)} /></label>
      <button disabled={!loaded} type="submit">Save spend walls</button>
    </form>
    <p role="status">{status}</p>
  </section>
}
