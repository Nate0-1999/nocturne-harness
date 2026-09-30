import type { CuratorActivityView } from './curation'

export function CuratorGrowth({ points }: { points: CuratorActivityView['growth'] }) {
  if (!points.length) return <p>Growth history is unavailable.</p>
  const latest = points[points.length - 1]
  const start = Date.parse(points[0].at)
  const span = Math.max(1, Date.parse(latest.at) - start)
  const maximum = Math.max(1, ...points.flatMap((point) => [point.active_units, point.curator_removals]))
  const line = (key: 'active_units' | 'curator_removals') => points.map((point) =>
    `${10 + (Date.parse(point.at) - start) / span * 380},${110 - point[key] / maximum * 100}`
  ).join(' ')
  return <figure className="curator-growth">
    <figcaption>Memory growth · {latest.active_units} active · {latest.curator_removals} curator removals</figcaption>
    {points.length > 1 ? <svg viewBox="0 0 400 120" role="img" aria-label="Active memory count and cumulative curator removals at each recorded pass">
      <polyline points={line('active_units')} fill="none" stroke="var(--accent)" strokeWidth="2" />
      <polyline points={line('curator_removals')} fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="5 4" />
    </svg> : null}
    <small>Solid: active memories. Dashed: cumulative removals. Snapshots at curator passes and now.</small>
    <details><summary>Growth measurements</summary>
      <table><thead><tr><th>Time</th><th>Active</th><th>Curator removals</th></tr></thead>
        <tbody>{points.map((point, index) => <tr key={index}>
          <td>{new Date(point.at).toLocaleString()}</td><td>{point.active_units}</td><td>{point.curator_removals}</td>
        </tr>)}</tbody>
      </table>
    </details>
  </figure>
}
