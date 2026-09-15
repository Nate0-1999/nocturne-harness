import { useEffect, useState } from 'react'

const ROLES = { chat: 'Agent', subagent: 'Sub-agent', judge: 'Judge' } as const

/** A-021 / FL-154: the same token-cost policy type, independently bound to each role. */
export function AgentPolicies() {
  const [policies, setPolicies] = useState<Record<string, string>>({})
  const [status, setStatus] = useState('Loading policies…')
  useEffect(() => {
    fetch('/v1/model-policies').then(async (response) => {
      if (!response.ok) throw new Error('Model policies are unavailable')
      setPolicies((await response.json()).policies)
      setStatus('Applies to new threads and future Symphony rounds. Existing thread choices stay fixed.')
    }).catch((error: Error) => setStatus(error.message))
  }, [])
  async function save(role: string) {
    try {
      const response = await fetch(`/v1/model-policies/${role}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ policy: policies[role] }),
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail ?? 'Policy could not be saved')
      setStatus(`${ROLES[role as keyof typeof ROLES]} policy saved. Existing thread choices stay fixed.`)
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Policy unavailable') }
  }
  return <section className="agent-policy-settings">
    <h2>Agent model policies</h2>
    <p role="status">{status}</p>
    {Object.entries(ROLES).map(([role, label]) => {
      const value = policies[role]
      if (value === undefined) return null
      const separator = value.indexOf(':')
      const kind = separator < 0 ? value : value.slice(0, separator)
      const argument = separator < 0 ? '' : value.slice(separator + 1)
      return <fieldset key={role}>
        <legend>{label}</legend>
        <label className="theme-control">Token-cost policy
          <select aria-label={`${label} token-cost policy`} value={kind} onChange={(event) => {
            const next = event.target.value
            setPolicies({ ...policies, [role]: next === 'pinned' ? 'pinned:' : next === 'floor' || next === 'slope' ? `${next}:1` : next })
          }}>
            <option value="pinned">Pinned</option><option value="max">Max</option>
            <option value="elbow">Elbow</option><option value="floor">Floor</option><option value="slope">Slope</option>
          </select>
        </label>
        {separator >= 0 && <label>{kind === 'pinned' ? 'Model' : kind === 'floor' ? 'Intelligence floor' : 'Price slope'}
          <input aria-label={`${label} policy value`} value={argument} onChange={(event) => setPolicies({ ...policies, [role]: `${kind}:${event.target.value}` })} />
        </label>}
        <div className="app-settings-actions"><button type="button" onClick={() => void save(role)}>Save {label.toLowerCase()} policy</button></div>
      </fieldset>
    })}
    <p>Curator policy is managed by the Palace and is unavailable here.</p>
  </section>
}
