import { useRackPlugin } from './rack'

export function InstrumentClose() {
  const { selection } = useRackPlugin()
  return (
    <button
      className="instrument-close"
      type="button"
      aria-label="Close instrument"
      onClick={() => selection.select(null)}
    >
      Close
    </button>
  )
}
