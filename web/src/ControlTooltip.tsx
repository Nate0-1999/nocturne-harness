import { useEffect, useLayoutEffect, useRef, useState } from 'react'

const CONTROL_SELECTOR = [
  'button',
  'input:not([type="hidden"])',
  'select',
  'textarea',
  '[role="button"]',
  '[role="slider"]',
  '[role="tab"]',
].join(',')

// M3W6B-37: every module frame keeps its own tip, and a frame the pointer jumps out of may
// never hear it leave. The document the pointer enters says so; every other one closes its tip.
const POINTER_HERE = 'nocturne.control-tooltip.pointer-here'

// SD-112 / M8LR: a finger cannot hover. Held this long on a control it raises the tip, and the lift
// after it presses nothing; a quicker tap presses as before. A text field's hold is the system's own.
const HOLD_MS = 500
const HOLD_SLOP_PX = 10
const TEXT_ENTRY = 'textarea, select, input:not([type="checkbox"], [type="radio"], [type="range"])'

interface TooltipState {
  title: string
  detail: string
  x: number
  y: number
  above: boolean
}

/** PLAN M2TC / P2 gives every approached control one calm, formatted explanation. */
export function ControlTooltip() {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)
  const tipRef = useRef<HTMLElement>(null)

  useEffect(() => {
    let activeControl: HTMLElement | null = null
    let pointerHere = false
    let holdTimer: ReturnType<typeof setTimeout> | undefined
    let holdFrom: { x: number, y: number } | null = null
    // A hold raised the tip: it stays up after the lift, until the next touch, and the lift's click is swallowed.
    let held = false
    const inFrame = window.parent !== window
    const frames = () => Array.from(document.querySelectorAll('iframe'), (frame) => frame.contentWindow)

    // The shell relays a frame's word to every other frame; a frame tells only the shell.
    function announce(except: MessageEventSource | null) {
      if (inFrame) window.parent.postMessage({ type: POINTER_HERE }, '*')
      else for (const frame of frames()) if (frame !== null && frame !== except) frame.postMessage({ type: POINTER_HERE }, '*')
    }

    function onMessage(event: MessageEvent) {
      if (event.data?.type !== POINTER_HERE) return
      if (inFrame ? event.source !== window.parent : !frames().includes(event.source as Window)) return
      if (!inFrame) announce(event.source)
      pointerHere = false
      hide(activeControl)
    }

    function show(control: HTMLElement) {
      activeControl = control
      setTooltip(positionTooltip(control))
    }

    function hide(control: HTMLElement | null) {
      if (control !== null && activeControl !== control) return
      activeControl = null
      setTooltip(null)
    }

    // M3EX-26: a tip never outlives the pointer. Over no control, leaving this
    // document (a module frame) or this window losing focus all hide it.
    function onPointerOver(event: PointerEvent) {
      if (!pointerHere) {
        pointerHere = true
        announce(null)
      }
      if (event.pointerType === 'touch') return
      const control = closestControl(event.target)
      if (control === null) hide(activeControl)
      else if (control !== activeControl) show(control)
    }

    function onLeave(event: Event) {
      pointerHere = false
      if (held && event.type !== 'blur') return
      hide(activeControl)
    }

    function onPointerOut(event: PointerEvent) {
      if (held) return
      const control = closestControl(event.target)
      if (control === null || closestControl(event.relatedTarget) === control) return
      hide(control)
    }

    function onFocusIn(event: FocusEvent) {
      const control = closestControl(event.target)
      // A click or a window regaining focus raises no tip; keyboard focus does.
      if (control !== null && control.matches(':focus-visible')) show(control)
    }

    function onFocusOut(event: FocusEvent) {
      const control = closestControl(event.target)
      if (control === null || closestControl(event.relatedTarget) === control) return
      hide(control)
    }

    function reposition() {
      if (activeControl !== null) setTooltip(positionTooltip(activeControl))
    }

    function onPointerDown(event: PointerEvent) {
      endHold()
      held = false
      if (event.pointerType !== 'touch') return
      hide(activeControl)
      const control = closestControl(event.target)
      if (control === null || control.matches(TEXT_ENTRY)) return
      holdFrom = { x: event.clientX, y: event.clientY }
      holdTimer = setTimeout(() => {
        held = true
        show(control)
      }, HOLD_MS)
    }

    function onPointerMove(event: PointerEvent) {
      if (holdFrom !== null && Math.hypot(event.clientX - holdFrom.x, event.clientY - holdFrom.y) > HOLD_SLOP_PX) endHold()
    }

    function endHold() {
      clearTimeout(holdTimer)
      holdFrom = null
    }

    function onActivate(event: MouseEvent) {
      // The lift after a hold: the tip was read and nothing is pressed. A keyboard press (detail 0) is never a lift.
      if (held && event.detail !== 0) {
        held = false
        event.preventDefault()
        event.stopPropagation()
        return
      }
      hide(activeControl)
    }

    document.addEventListener('pointerover', onPointerOver)
    document.addEventListener('pointerout', onPointerOut)
    document.addEventListener('focusin', onFocusIn)
    document.addEventListener('focusout', onFocusOut)
    document.addEventListener('click', onActivate, true)
    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('pointermove', onPointerMove, true)
    document.addEventListener('pointerup', endHold, true)
    document.addEventListener('pointercancel', endHold, true)
    document.documentElement.addEventListener('pointerleave', onLeave)
    globalThis.addEventListener('blur', onLeave)
    globalThis.addEventListener('message', onMessage)
    globalThis.addEventListener('resize', reposition)
    globalThis.addEventListener('scroll', reposition, true)
    return () => {
      document.removeEventListener('pointerover', onPointerOver)
      document.removeEventListener('pointerout', onPointerOut)
      document.removeEventListener('focusin', onFocusIn)
      document.removeEventListener('focusout', onFocusOut)
      document.removeEventListener('click', onActivate, true)
      document.removeEventListener('pointerdown', onPointerDown, true)
      document.removeEventListener('pointermove', onPointerMove, true)
      document.removeEventListener('pointerup', endHold, true)
      document.removeEventListener('pointercancel', endHold, true)
      endHold()
      document.documentElement.removeEventListener('pointerleave', onLeave)
      globalThis.removeEventListener('blur', onLeave)
      globalThis.removeEventListener('message', onMessage)
      globalThis.removeEventListener('resize', reposition)
      globalThis.removeEventListener('scroll', reposition, true)
    }
  }, [])

  useLayoutEffect(() => {
    const tip = tipRef.current
    if (tip === null || tooltip === null) return
    // M3W5B-37: a wide tip beside an edge slides inward instead of being cut off.
    const rect = tip.getBoundingClientRect()
    const shift = Math.max(12 - rect.left, 0) - Math.max(rect.right - (globalThis.innerWidth - 12), 0)
    if (shift !== 0) tip.style.left = `${tooltip.x + shift}px`
  }, [tooltip])

  if (tooltip === null) return null
  return (
    <aside
      ref={tipRef}
      className="control-tooltip"
      data-placement={tooltip.above ? 'above' : 'below'}
      role="tooltip"
      style={{ left: tooltip.x, top: tooltip.y }}
    >
      <strong>{tooltip.title}</strong>
      {tooltip.detail !== '' && <span>{tooltip.detail}</span>}
    </aside>
  )
}

function closestControl(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof Element)) return null
  return target.closest<HTMLElement>(CONTROL_SELECTOR)
}

function positionTooltip(control: HTMLElement): TooltipState {
  const rect = control.getBoundingClientRect()
  const above = rect.bottom + 96 > globalThis.innerHeight && rect.top > 96
  return {
    title: controlTitle(control),
    detail: controlDetail(control),
    x: Math.max(12, Math.min(globalThis.innerWidth - 12, rect.left + rect.width / 2)),
    y: above ? rect.top - 8 : rect.bottom + 8,
    above,
  }
}

function controlTitle(control: HTMLElement): string {
  const explicit = normalize(control.dataset.tooltip)
  if (explicit !== '') return explicit
  const aria = normalize(control.getAttribute('aria-label'))
  if (aria !== '') return aria
  const labelled = normalize((control.getAttribute('aria-labelledby') ?? '')
    .split(/\s+/u)
    .map((id) => document.getElementById(id)?.textContent ?? '')
    .join(' '))
  if (labelled !== '') return labelled
  if (
    control instanceof HTMLInputElement ||
    control instanceof HTMLSelectElement ||
    control instanceof HTMLTextAreaElement
  ) {
    const label = normalize(Array.from(control.labels ?? []).map((item) => item.textContent).join(' '))
    if (label !== '') return label
    const placeholder = normalize(control.getAttribute('placeholder'))
    if (placeholder !== '') return placeholder
  }
  const text = normalize(control.textContent)
  return text === '' ? 'Control' : text
}

function controlDetail(control: HTMLElement): string {
  const explicit = normalize(control.dataset.tooltipDetail)
  if (explicit !== '') return explicit
  const described = normalize((control.getAttribute('aria-describedby') ?? '')
    .split(/\s+/u)
    .map((id) => document.getElementById(id)?.textContent ?? '')
    .join(' '))
  if (described !== '') return described
  const title = normalize(control.getAttribute('title'))
  if (title !== '' && title !== controlTitle(control)) return title
  if (control.getAttribute('role') === 'tab') return 'Switch to this stage layer.'
  // M3W5B-36: no filler; a control without its own explanation shows its name alone.
  return ''
}

function normalize(value: string | null | undefined): string {
  return (value ?? '').replace(/\s+/gu, ' ').trim()
}
