import { speechSentences } from './speechText'

export const readingRates = [1, 1.25, 1.5, 2, 2.5, 3]
export function storedRate(scope: string | undefined) {
  const rate = Number(localStorage.getItem(`nocturne.reading-rate:${scope}`))
  return readingRates.includes(rate) ? rate : 1
}

interface Reading {
  id: string
  source: string
  finished: boolean
  rate: number
  paused: boolean
  index: number
  offset: number
  sentences?: string[]
}

let reading: Reading | null = null
let utterance: SpeechSynthesisUtterance | null = null
let errorId: string | null = null
const listeners = new Set<() => void>()
function notify() { for (const listener of listeners) listener() }
function cancelUtterance() {
  if (!utterance) return
  utterance.onend = utterance.onerror = utterance.onboundary = null
  utterance = null
  speechSynthesis.cancel()
}

function advance() {
  if (!reading || reading.paused || utterance) return
  const session = reading
  session.sentences ??= speechSentences(session.source, session.finished)
  const sentence = session.sentences[session.index]
  if (!sentence) {
    if (session.finished) {
      reading = null
      notify()
      dispatchEvent(new Event('out-loud-finished'))
    }
    return
  }
  const start = session.offset
  const speech = new SpeechSynthesisUtterance(sentence.slice(start))
  utterance = speech
  speech.lang = document.documentElement.lang || navigator.language
  speech.rate = session.rate
  speech.onboundary = event => {
    if (utterance === speech && event.name === 'word') session.offset = start + event.charIndex
  }
  speech.onend = () => {
    if (utterance !== speech) return
    utterance = null
    session.index++
    session.offset = 0
    advance()
  }
  speech.onerror = () => {
    if (utterance !== speech) return
    errorId = session.id
    utterance = reading = null
    notify()
  }
  speechSynthesis.speak(speech)
}

export const reader = {
  subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener) } },
  state(id: string) { return reading?.id === id ? (reading.paused ? 'paused' : 'reading') : errorId === id ? 'error' : 'idle' },
  active() { return reading !== null },
  phase() { return reading ? (reading.paused ? 'paused' : 'reading') : 'idle' },
  start(id: string, source: string, finished: boolean, rate: number) {
    cancelUtterance()
    errorId = null
    reading = { id, source, finished, rate, paused: false, index: 0, offset: 0 }
    dispatchEvent(new Event('out-loud-reading'))
    notify()
    advance()
  },
  update(id: string, source: string, finished: boolean) {
    if (reading?.id !== id) return
    if (reading.source !== source || reading.finished !== finished) reading.sentences = undefined
    reading.source = source
    reading.finished = finished
    advance()
  },
  stop(id: string) {
    if (reading?.id !== id) return
    cancelUtterance()
    reading = null
    notify()
  },
  interrupt() { if (reading) reader.stop(reading.id) },
  speed(rate: number) {
    if (!reading || rate === reading.rate) return
    reading.rate = rate
    cancelUtterance()
    advance()
  },
  pause() {
    if (!reading) return
    reading.paused = !reading.paused
    if (reading.paused) cancelUtterance()
    else advance()
    notify()
  },
  skip() {
    if (!reading) return
    cancelUtterance()
    reading.index++
    reading.offset = 0
    advance()
  },
}
