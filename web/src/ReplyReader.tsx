import { useEffect, useSyncExternalStore } from 'react'
import { Button, Select } from './kit'
import { useRackSnapshot } from './rack'
import { reader, readingRates, storedRate } from './speechReader'

function subscribeRate(listener: () => void) {
  window.addEventListener('storage', listener)
  window.addEventListener('out-loud-rate', listener)
  return () => {
    window.removeEventListener('storage', listener)
    window.removeEventListener('out-loud-rate', listener)
  }
}

export function ReadingSpeed() {
  const { preferenceScope } = useRackSnapshot()
  const rate = useSyncExternalStore(subscribeRate, () => storedRate(preferenceScope))
  return <Select aria-label="Reading speed" title="Change reading speed" value={rate} onChange={event => {
    const next = Number(event.target.value)
    localStorage.setItem(`nocturne.reading-rate:${preferenceScope}`, String(next))
    reader.speed(next)
    dispatchEvent(new Event('out-loud-rate'))
  }}>
    {readingRates.map(speed => <option key={speed} value={speed}>{speed}×</option>)}
  </Select>
}

export function ReplyReader({ id, text, finished = true }: { id: string; text: string; finished?: boolean }) {
  const { preferenceScope } = useRackSnapshot()
  const phase = useSyncExternalStore(reader.subscribe, () => reader.state(id))
  useEffect(() => {
    reader.update(id, text, finished)
  }, [id, text, finished])
  useEffect(() => () => reader.stop(id), [id])
  if (!('speechSynthesis' in window) || !text.trim()) return null
  const active = phase === 'reading' || phase === 'paused'
  return <div className="out-loud" aria-label="Reply playback">
    {active ? <>
      <ReadingSpeed />
      <Button type="button" iconOnly action={phase === 'paused' ? 'run' : 'pause'}
        data-tooltip={phase === 'paused' ? 'Resume reading' : 'Pause reading'}
        title={phase === 'paused' ? 'Resume reading' : 'Pause reading'} onClick={reader.pause} />
      <Button type="button" action="next" iconOnly data-tooltip="Skip sentence" title="Skip sentence" onClick={reader.skip} />
      <Button type="button" action="stop" iconOnly data-tooltip="Stop reading" title="Stop reading" onClick={() => reader.stop(id)} />
    </> : <Button action="speak" iconOnly type="button" data-tooltip="Read aloud" title="Read this reply aloud"
      onClick={() => reader.start(id, text, finished, storedRate(preferenceScope))} />}
    {phase === 'error' && <small role="status">Playback stopped. Tap Read aloud to retry.</small>}
  </div>
}
