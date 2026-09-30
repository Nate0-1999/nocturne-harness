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
      const control = closestControl(event.target)
      if (control === null) hide(activeControl)
      else if (control !== activeControl) show(control)
    }

    function onLeave() {
      hide(activeControl)
    }

    function onPointerOut(event: PointerEvent) {
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

    function onActivate() {
      hide(activeControl)
    }

    document.addEventListener('pointerover', onPointerOver)
    document.addEventListener('pointerout', onPointerOut)
    document.addEventListener('focusin', onFocusIn)
    document.addEventListener('focusout', onFocusOut)
    document.addEventListener('click', onActivate, true)
    document.documentElement.addEventListener('pointerleave', onLeave)
    globalThis.addEventListener('blur', onLeave)
    globalThis.addEventListener('resize', reposition)
    globalThis.addEventListener('scroll', reposition, true)
    return () => {
      document.removeEventListener('pointerover', onPointerOver)
      document.removeEventListener('pointerout', onPointerOut)
      document.removeEventListener('focusin', onFocusIn)
      document.removeEventListener('focusout', onFocusOut)
      document.removeEventListener('click', onActivate, true)
      document.documentElement.removeEventListener('pointerleave', onLeave)
      globalThis.removeEventListener('blur', onLeave)
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
