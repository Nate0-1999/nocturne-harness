/** SD-115: a stationary touch reveals the pin and consumes that touch's model tap. */
export function attachModelPinHold(list: HTMLElement | null) {
  if (!list) return
  const controller = new AbortController()
  const { signal } = controller
  let timer: number | undefined
  let start: Touch | undefined
  let revealed: Element | null = null
  let held = false

  function cancel() {
    window.clearTimeout(timer)
    start = undefined
  }
  function dismiss() {
    cancel()
    revealed?.removeAttribute('data-show-pin')
    revealed = null
    held = false
  }
  document.addEventListener('touchstart', event => {
    const target = event.target
    if (!(target instanceof Element)) return
    const pin = target.closest('.kit-button--pin')
    if (event.touches.length === 1 && pin && revealed?.contains(pin)) return
    dismiss()
    const row = target.closest('li.model-row')
    if (event.touches.length !== 1 || pin || !row || !list.contains(row)
        || !row.querySelector('.kit-button--pin[aria-pressed="false"]')) return
    start = event.touches[0]
    timer = window.setTimeout(() => {
      row.setAttribute('data-show-pin', '')
      revealed = row
      held = true
    }, 500)
  }, { capture: true, passive: true, signal })
  list.addEventListener('touchmove', event => {
    const touch = event.touches[0]
    if (start && touch && Math.hypot(touch.clientX - start.clientX, touch.clientY - start.clientY) > 10) cancel()
  }, { passive: true, signal })
  list.addEventListener('contextmenu', event => {
    if (start || held) event.preventDefault()
  }, { signal })
  list.addEventListener('touchend', event => {
    if (held) event.preventDefault()
    held = false
    cancel()
  }, { passive: false, signal })
  list.addEventListener('touchcancel', dismiss, { signal })
  list.addEventListener('click', event => {
    if (event.target instanceof Element && event.target.closest('.kit-button--pin')) dismiss()
  }, { signal })
  document.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'touch') dismiss()
  }, { capture: true, signal })
  window.addEventListener('blur', dismiss, { signal })
  return () => { controller.abort(); dismiss() }
}
