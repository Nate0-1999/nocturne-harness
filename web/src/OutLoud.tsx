import { useEffect, useRef, useState, useSyncExternalStore, type RefObject } from 'react'
import { useRackSnapshot } from './rack'
import './assets/out-loud.css'
import { Button } from './kit'

// Web Speech's recognition types are not yet included in TypeScript's DOM library.
interface Recognition extends EventTarget {
  lang: string
  continuous: boolean
  interimResults: boolean
  start(): void
  stop(): void
  abort(): void
  onresult: ((event: { results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
  onaudiostart: (() => void) | null
}
const SpeechRecognition = (globalThis as typeof globalThis & {
  SpeechRecognition?: new () => Recognition
  webkitSpeechRecognition?: new () => Recognition
}).SpeechRecognition ?? (globalThis as typeof globalThis & {
  webkitSpeechRecognition?: new () => Recognition
}).webkitSpeechRecognition

function subscribePreference(listener: () => void) {
  addEventListener('storage', listener)
  addEventListener('out-loud-preference', listener)
  return () => {
    removeEventListener('storage', listener)
    removeEventListener('out-loud-preference', listener)
  }
}

/** PLAN M3OU / SD-048, SD-063: speech uses the ordinary composer and send rule. */
export function OutLoud({ field, response, responseId, blocked, onDraft, onSend, replaceDraft = false, responding = false }: {
  field: RefObject<HTMLTextAreaElement | null>
  response: string
  responseId: string | null
  blocked: boolean
  onDraft: (text: string) => void
  onSend: () => void
  replaceDraft?: boolean
  responding?: boolean
}) {
  const supported = SpeechRecognition !== undefined && 'speechSynthesis' in globalThis
  const { preferenceScope } = useRackSnapshot()
  const preferenceKey = preferenceScope && !preferenceScope.endsWith(':unbound')
    ? `nocturne.out-loud:${preferenceScope}` : null
  const preferred = useSyncExternalStore(subscribePreference,
    () => preferenceKey !== null && localStorage.getItem(preferenceKey) === 'true', () => false)
  const enabled = supported && preferred
  const [phase, setPhase] = useState<'idle' | 'speaking' | 'listening'>('idle')
  const [status, setStatus] = useState('')
  const recognition = useRef<Recognition | null>(null)
  const utterance = useRef<SpeechSynthesisUtterance | null>(null)
  const sendFrame = useRef<number | null>(null)
  const spoken = useRef<string | null>(null)
  const onDraftRef = useRef(onDraft)
  const onSendRef = useRef(onSend)
  useEffect(() => { onDraftRef.current = onDraft }, [onDraft])
  useEffect(() => { onSendRef.current = onSend }, [onSend])

  function setEnabled(value: boolean) {
    if (preferenceKey) localStorage.setItem(preferenceKey, String(value))
    dispatchEvent(new Event('out-loud-preference'))
  }

  function stop() {
    if (sendFrame.current !== null) cancelAnimationFrame(sendFrame.current)
    sendFrame.current = null
    const current = recognition.current
    recognition.current = null
    if (current !== null) {
      current.onaudiostart = current.onend = current.onresult = current.onerror = null
      current.abort()
    }
    if (utterance.current !== null) {
      utterance.current.onstart = utterance.current.onend = utterance.current.onerror = null
      utterance.current = null
      speechSynthesis.cancel()
    }
  }

  function listen() {
    stop()
    const input = field.current
    if (!SpeechRecognition || blocked || input === null) return
    const before = replaceDraft ? '' : input.value.slice(0, input.selectionStart)
    const after = replaceDraft ? '' : input.value.slice(input.selectionEnd)
    const current = new SpeechRecognition()
    recognition.current = current
    current.lang = document.documentElement.lang || navigator.language
    current.continuous = true
    current.interimResults = true
    let processed = 0
    const dictated: string[] = []
    current.onaudiostart = () => setStatus('Listening. Say “Send” on its own to send your reply.')
    current.onresult = (event) => {
      const results = Array.from(event.results)
      for (; processed < results.length && results[processed].isFinal; processed++) {
        const text = results[processed][0].transcript.trim()
        if (/^send[.!?]?$/i.test(text)) {
          if (dictated.length) onDraftRef.current(before + dictated.join(' ') + after)
          stop()
          setPhase('idle')
          setStatus('Sending through the usual composer control…')
          sendFrame.current = requestAnimationFrame(() => {
            sendFrame.current = null
            onSendRef.current()
          })
          return
        }
        dictated.push(text)
      }
      const final = dictated.join(' ')
      const interim = results.filter((result) => !result.isFinal).map((result) => result[0].transcript).join(' ')
      if (final) {
        const text = before + final + after
        onDraftRef.current(text)
        requestAnimationFrame(() => {
          input.focus()
          input.setSelectionRange(before.length + final.length, before.length + final.length)
        })
      }
      setStatus(interim || 'Say “Send” on its own, or use the usual send control.')
    }
    current.onerror = (event) => {
      const reasons: Record<string, string> = {
        'not-allowed': 'Microphone access is blocked. Allow it in your browser, then tap Listen.',
        'service-not-allowed': 'Speech recognition is unavailable in this browser.',
        'audio-capture': 'No microphone is available. Connect one, then tap Listen.',
        network: 'The browser’s speech service could not connect. Tap Listen to retry.',
        'no-speech': 'No speech heard. Tap Listen to try again.',
        aborted: 'Listening stopped.',
      }
      setStatus(reasons[event.error] ?? 'Speech recognition stopped. Tap Listen to retry.')
    }
    current.onend = () => {
      recognition.current = null
      setPhase('idle')
    }
    try {
      current.start()
      setPhase('listening')
      setStatus('Opening microphone…')
    } catch {
      stop()
      setPhase('idle')
      setStatus('Listening could not start. Tap Listen to retry.')
    }
  }

  useEffect(() => {
    const input = field.current
    const pauseForTyping = () => {
      stop()
      setPhase('idle')
      setStatus('Dictation paused while editing. Tap Listen to resume.')
    }
    input?.addEventListener('input', pauseForTyping)
    return () => input?.removeEventListener('input', pauseForTyping)
  }, [field])

  function read() {
    stop()
    const speech = new SpeechSynthesisUtterance(response)
    utterance.current = speech
    speech.lang = document.documentElement.lang || navigator.language
    speech.onstart = () => { setPhase('speaking'); setStatus('Reading aloud…') }
    speech.onend = () => { utterance.current = null; listen() }
    speech.onerror = (event) => {
      utterance.current = null
      setPhase('idle')
      setStatus(event.error === 'not-allowed'
        ? 'Tap Read aloud to allow playback in this browser.'
        : 'Playback stopped. Tap Read aloud to retry.')
    }
    speechSynthesis.speak(speech)
  }

  useEffect(() => {
    if (!enabled || !supported || blocked || responding) return
    if (responseId !== null && response.trim() && spoken.current !== responseId) {
      spoken.current = responseId
      read()
    } else {
      listen()
    }
    return stop
    // Callbacks belong to this response; draft edits must not restart the microphone.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, supported, blocked, responding, responseId, response])

  return (
    <div className="out-loud" data-testid="out-loud">
      <div role="group" aria-label="Input mode">
        <Button type="button" aria-pressed={!enabled} onClick={() => {
          stop(); setPhase('idle'); setStatus(''); setEnabled(false)
        }}>Typing</Button>
        <Button type="button" aria-pressed={enabled} disabled={!supported || preferenceKey === null}
          onClick={() => {
            setEnabled(true)
          }}>Out Loud</Button>
      </div>
      {!supported && <small>This browser does not support Out Loud. Typing is available.</small>}
      {enabled && <>
        <Button type="button" disabled={blocked} onClick={() => {
          if (phase === 'listening') {
            recognition.current?.stop()
            setStatus('Listening stopped.')
          } else {
            listen()
          }
        }}>{phase === 'speaking' ? 'Interrupt and listen' : phase === 'listening' ? 'Stop listening' : 'Listen'}</Button>
        {response.trim() && <Button type="button" disabled={blocked} onClick={read}>Read aloud</Button>}
        <small role="status">{blocked ? 'Waiting for the conversation…'
          : responding && phase === 'idle' ? 'Reply running. Tap Listen to dictate.' : status}</small>
      </>}
    </div>
  )
}
