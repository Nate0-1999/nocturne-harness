import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import type { MemoryFeatures } from './protocol'
import { formatHumanScore } from './humanNumbers'

/** Owner, 2026-09-22: a memory card shows score, name and memory; the relevance
 * features pop up as a spider-web chart on hover, for those who want to look. */
const RADAR_AXES: readonly { key: keyof MemoryFeatures; label: string }[] = [
  { key: 'sem', label: 'Semantic' },
  { key: 'kw', label: 'Keyword' },
  { key: 'time', label: 'Recency' },
  { key: 'proj', label: 'Project' },
  { key: 'thread', label: 'Thread' },
  { key: 'loc', label: 'Location' },
  { key: 'where', label: 'Where' },
  { key: 'freq', label: 'Citation' },
  { key: 'hist', label: 'Edit history' },
]

const SIZE = 260
const CENTER = SIZE / 2
const RADIUS = 88

function point(index: number, magnitude: number): [number, number] {
  const angle = -Math.PI / 2 + (index / RADAR_AXES.length) * Math.PI * 2
  return [CENTER + Math.cos(angle) * RADIUS * magnitude, CENTER + Math.sin(angle) * RADIUS * magnitude]
}

function polygon(values: readonly number[]): string {
  return values.map((value, index) => point(index, Math.min(1, Math.max(0, value))).join(',')).join(' ')
}

export function FeatureRadar({ features, contributions }: {
  features?: MemoryFeatures | null
  contributions?: Record<string, string | null> | null
}) {
  const raw = features == null ? null : RADAR_AXES.map(({ key }) => Number(features[key] ?? 0))
  const weighted = contributions == null ? null : RADAR_AXES.map(({ key }) => Number(contributions[key] ?? 0))
  const weightedMax = weighted === null ? 1 : Math.max(...weighted.map(Math.abs), 0.001)
  return (
    <figure className="feature-radar" aria-label="Relevance features">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="Raw feature scores on a spider web">
        {[0.25, 0.5, 0.75, 1].map((ring) => (
          <polygon key={ring} className="feature-radar__ring" points={polygon(RADAR_AXES.map(() => ring))} />
        ))}
        {RADAR_AXES.map((axis, index) => {
          const [x, y] = point(index, 1)
          const [lx, ly] = point(index, 1.24)
          return (
            <g key={axis.key}>
              <line className="feature-radar__spoke" x1={CENTER} y1={CENTER} x2={x} y2={y} />
              <text className="feature-radar__label" x={lx} y={ly} textAnchor="middle" dominantBaseline="middle">{axis.label}</text>
            </g>
          )
        })}
        {weighted !== null && (
          <polygon className="feature-radar__weighted" points={polygon(weighted.map((value) => Math.abs(value) / weightedMax))} />
        )}
        {raw !== null && <polygon className="feature-radar__raw" points={polygon(raw)} />}
        {raw?.map((value, index) => {
          const [x, y] = point(index, Math.min(1, Math.max(0, value)))
          return <circle key={RADAR_AXES[index].key} className="feature-radar__dot" cx={x} cy={y} r={2.4} />
        })}
      </svg>
      <figcaption>
        {RADAR_AXES.map(({ key, label }, index) => (
          <span key={key}>
            <span>{label}</span>
            <strong>{raw === null || features?.[key] === null ? '—' : formatHumanScore(raw[index])}</strong>
            {weighted !== null && <em>{contributions?.[key] === null ? '—' : formatHumanScore(weighted[index])}</em>}
          </span>
        ))}
        <small>{raw === null ? 'Weighted contribution' : weighted === null ? 'Raw features · not weighted yet' : 'Raw features · weighted contribution'}</small>
      </figcaption>
    </figure>
  )
}

/** Shows `panel` beside `anchor` while the pointer or focus rests on the children. */
export function HoverReveal({ children, panel, className }: {
  children: ReactNode
  panel: ReactNode
  className?: string
}) {
  const anchor = useRef<HTMLDivElement>(null)
  const reveal = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [placement, setPlacement] = useState<{ x: number; y: number; above: boolean; room: number; scroll: boolean } | null>(null)

  // M4VW: the panel is measured, never assumed (a fixed 340 px guess ran long histories off the
  // module): it takes the side it fits on, else the roomier side, capped there and scrollable.
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const rect = anchor.current?.getBoundingClientRect()
      const panel = reveal.current
      if (rect === undefined || panel === null) return
      const below = globalThis.innerHeight - rect.bottom - 4
      const above = rect.top - 4
      const up = panel.scrollHeight > below && above > below
      const half = Math.min(panel.offsetWidth, globalThis.innerWidth - 8) / 2 + 4
      const room = Math.max(0, up ? above : below)
      setPlacement({
        // The panel is centred on the title and kept on screen by its measured half width.
        x: Math.max(half, Math.min(globalThis.innerWidth - half, rect.left + rect.width / 2)),
        y: up ? rect.top : rect.bottom,
        above: up,
        room,
        // Only a panel taller than its room takes the pointer, so it can be scrolled.
        scroll: panel.scrollHeight > room,
      })
    }
    place()
    globalThis.addEventListener('scroll', place, true)
    globalThis.addEventListener('resize', place)
    return () => {
      globalThis.removeEventListener('scroll', place, true)
      globalThis.removeEventListener('resize', place)
    }
  }, [open])
  const show = () => setOpen(true)
  const hide = () => { setOpen(false); setPlacement(null) }

  return (
    <div
      ref={anchor}
      className={className}
      onPointerEnter={show}
      onPointerLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}
      {open && (
        <div
          ref={reveal}
          className="hover-reveal"
          data-placement={placement === null ? undefined : placement.above ? 'above' : 'below'}
          data-scroll={placement?.scroll || undefined}
          style={placement === null ? undefined : { left: placement.x, top: placement.y, maxHeight: placement.room }}
        >
          {panel}
        </div>
      )}
    </div>
  )
}
