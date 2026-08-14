import { useEffect, useState } from 'react'

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

    function onPointerOver(event: PointerEvent) {
      const control = closestControl(event.target)
      if (control !== null && control !== activeControl) show(control)
    }

    function onPointerOut(event: PointerEvent) {
      const control = closestControl(event.target)
      if (control === null || closestControl(event.relatedTarget) === control) return
      hide(control)
    }

    function onFocusIn(event: FocusEvent) {
      const control = closestControl(event.target)
      if (control !== null) show(control)
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
    globalThis.addEventListener('resize', reposition)
    globalThis.addEventListener('scroll', reposition, true)
    return () => {
      document.removeEventListener('pointerover', onPointerOver)
      document.removeEventListener('pointerout', onPointerOut)
      document.removeEventListener('focusin', onFocusIn)
      document.removeEventListener('focusout', onFocusOut)
      document.removeEventListener('click', onActivate, true)
      globalThis.removeEventListener('resize', reposition)
      globalThis.removeEventListener('scroll', reposition, true)
    }
  }, [])

  if (tooltip === null) return null
  return (
    <aside
      className="control-tooltip"
      data-placement={tooltip.above ? 'above' : 'below'}
      role="tooltip"
      style={{ left: tooltip.x, top: tooltip.y }}
    >
      <strong>{tooltip.title}</strong>
      <span>{tooltip.detail}</span>
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
  if (control.getAttribute('role') === 'tab') return 'Switch to this stage layer.'
  if (control instanceof HTMLSelectElement) return 'Choose one of the available options.'
  if (control instanceof HTMLTextAreaElement) return 'Enter text for this action.'
  if (control instanceof HTMLInputElement) {
    if (control.type === 'range') return 'Adjust this value; the current value remains visible.'
    if (control.type === 'file') return 'Choose a local file for this action.'
    return 'Enter or change this value.'
  }
  if (control.getAttribute('role') === 'button') return 'Activate it here or with the keyboard.'
  return 'Activate this control.'
}

function normalize(value: string | null | undefined): string {
  return (value ?? '').replace(/\s+/gu, ' ').trim()
}
