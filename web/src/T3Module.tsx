import { useEffect, useRef, useState } from 'react'
import { Button } from './kit'
import { createHostPluginApi, getRackSnapshot, RACK_MANIFESTS, RackApiProvider, useRackHostSnapshot } from './rack'
import { BoundaryCards } from './SymphonyDeck'
import { T3ProjectImport } from './T3ProjectImport'

// `load` counts the addresses sent to the frame: the same address again is still a fresh load.
type Screen = { url: string, load: number } | { line: string } | null

const host = createHostPluginApi(RACK_MANIFESTS.t3)
// The host page's own snapshot is the same object until the store changes; a hook can hold it.
const api = { ...host, events: { ...host.events, getSnapshot: getRackSnapshot } }

/** SD-114: T3 Code's own screen. The daemon passes T3 through and admits this page alone (A-101),
 * so the host page frames it directly; a rack frame's address would be refused.
 * SD-124: it stays in step with the Stage's open thread, both ways. */
export function T3Module() {
  const { selectedThreadId: open, catalog } = useRackHostSnapshot()
  const [screen, setScreen] = useState<Screen>(null)
  const [attempt, setAttempt] = useState(0)
  const [unanswered, setUnanswered] = useState('')
  // The journal thread T3's page is on, as far as this page knows: where it last sent T3, or
  // where the daemon last saw T3 go. `seen` is the daemon's last word, so only a move counts.
  const at = useRef<string | null>(null)
  const seen = useRef<string | null>(null)
  const [imported, setImported] = useState<string | null>(null)
  const openingImport = useRef<string | null>(null)
  useEffect(() => {
    if (imported && catalog.some(row => row.thread_id === imported)) {
      openingImport.current = imported
      void api.events.dispatch({ type: 'thread.select', thread_id: imported })
      setImported(null)
    }
  }, [imported, catalog])
  const phase = screen === null ? 'starting' : 'url' in screen ? 'shown' : 'stopped'

  useEffect(() => {
    if (phase === 'stopped' || (phase === 'shown' && (open === null || open === at.current))) return
    let current = true
    const query = new URLSearchParams()
    if (open !== null) query.set('thread', open)
    if (phase === 'shown') query.set('paired', 'true')
    globalThis.fetch(`/v1/t3/front/frame?${query}`, { method: 'POST' })
      .then(async (response) => {
        const body = await response.json() as { url?: string | null, line?: string, detail?: string }
        return body.url ? { url: body.url, load: Date.now() } : { line: body.line ?? body.detail ?? 'T3 did not start.' }
      })
      .catch(() => ({ line: 'Nocturne is not answering. Run nocturne up.' }))
      .then((next) => {
        // A shown T3 that cannot open this thread yet stays where it is.
        if (!current) return
        if (phase === 'shown' && 'line' in next) {
          if (openingImport.current === open) openingImport.current = null
          return
        }
        at.current = open
        setScreen(next)
      })
    return () => { current = false }
  }, [attempt, open, phase])

  useEffect(() => {
    if (phase !== 'shown') return
    const timer = globalThis.setInterval(() => {
      globalThis.fetch('/v1/t3/front/frame', { cache: 'no-store' })
        .then((response) => response.json() as Promise<{ running: boolean, thread?: string | null }>)
        .then(({ running, thread }) => {
          if (!running) {
            at.current = seen.current = null
            setScreen({ line: 'T3 stopped.' })
          } else if (openingImport.current && openingImport.current === getRackSnapshot().selectedThreadId) {
            // The old iframe can still report its thread while the imported address loads.
            if (thread === openingImport.current) {
              seen.current = thread
              openingImport.current = null
            }
          } else if (thread && thread !== seen.current &&
            getRackSnapshot().catalog.some((entry) => entry.thread_id === thread)) {
            // A thread opened in T3 becomes the Stage's open thread, once the thread list has it.
            seen.current = thread
            if (thread !== at.current) {
              at.current = thread
              void api.events.dispatch({ type: 'thread.select', thread_id: thread })
            }
          }
        })
        .catch(() => setScreen({ line: 'Nocturne is not answering. Run nocturne up.' }))
    }, 1000)
    return () => globalThis.clearInterval(timer)
  }, [phase])

  if (screen === null) return <p className="t3-module__line" role="status">Starting T3…</p>
  if ('line' in screen) {
    return (
      <p className="t3-module__line" role="status" data-testid="t3-module-line">
        <span>{screen.line}</span>
        <Button
          action="run"
          type="button"
          data-tooltip-detail="Start T3 on this machine and show it here."
          onClick={() => { setScreen(null); setAttempt((value) => value + 1) }}
        >
          Run T3
        </Button>
      </p>
    )
  }
  // T3 keeps what its own window has, except leaving this frame: it cannot move Nocturne's page.
  return (
    <div className="t3-project-window">
      <T3ProjectImport onOpen={setImported} />
      {/* A crossing asked for from T3 waits on the Deck; the same card is answered here too. */}
      <div className="t3-module__crossing" data-testid="t3-module-crossing">
        <RackApiProvider api={api}>
          <BoundaryCards onFailure={setUnanswered} />
        </RackApiProvider>
        {unanswered !== '' && <p role="status">{unanswered}</p>}
      </div>
      <iframe
        key={screen.load}
        className="rack-plugin-frame t3-module__frame"
        data-testid="t3-module-frame"
        title="T3"
        src={screen.url}
        sandbox="allow-scripts allow-same-origin allow-forms allow-modals allow-popups allow-downloads"
        allow="clipboard-read; clipboard-write; microphone"
      />
    </div>
  )
}
