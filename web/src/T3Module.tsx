import { useEffect, useState } from 'react'
import { Button } from './kit'

type Screen = { url: string } | { line: string } | null

/** SD-114: T3 Code's own screen. The daemon passes T3 through and admits this page alone (A-101),
 * so the host page frames it directly; a rack frame's address would be refused. */
export function T3Module() {
  const [screen, setScreen] = useState<Screen>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let current = true
    globalThis.fetch('/v1/t3/front/frame', { method: 'POST' })
      .then(async (response) => {
        const body = await response.json() as { url?: string, line?: string, detail?: string }
        return body.url ? { url: body.url } : { line: body.line ?? body.detail ?? 'T3 did not start.' }
      })
      .catch(() => ({ line: 'Nocturne is not answering. Run nocturne up.' }))
      .then((next) => { if (current) setScreen(next) })
    return () => { current = false }
  }, [attempt])

  const shown = screen !== null && 'url' in screen
  useEffect(() => {
    if (!shown) return
    const timer = globalThis.setInterval(() => {
      globalThis.fetch('/v1/t3/front/frame', { cache: 'no-store' })
        .then((response) => response.json() as Promise<{ running: boolean }>)
        .then((state) => { if (!state.running) setScreen({ line: 'T3 stopped.' }) })
        .catch(() => setScreen({ line: 'Nocturne is not answering. Run nocturne up.' }))
    }, 4000)
    return () => globalThis.clearInterval(timer)
  }, [shown])

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
    <iframe
      className="rack-plugin-frame t3-module__frame"
      data-testid="t3-module-frame"
      title="T3"
      src={screen.url}
      sandbox="allow-scripts allow-same-origin allow-forms allow-modals allow-popups allow-downloads"
      allow="clipboard-read; clipboard-write; microphone"
    />
  )
}
