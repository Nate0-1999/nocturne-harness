import { useState } from 'react'
import { parseRackPlugin, saveRackPlugin, type CustomRackModuleId } from './rackPlugins'
import { registerRackPlugin } from './rack'
import { registerStagePlugin } from './stageLayout'

/** FL-105: import one self-contained plugin through the shared rack contract. */
export function RackPluginUpload({ onInstalled }: { onInstalled: (id: CustomRackModuleId) => void }) {
  const [source, setSource] = useState('')
  const [status, setStatus] = useState('Choose or paste a plugin JSON bundle.')
  function install(text: string) {
    try {
      const plugin = parseRackPlugin(JSON.parse(text))
      saveRackPlugin(plugin)
      registerRackPlugin(plugin)
      registerStagePlugin(plugin.id)
      onInstalled(plugin.id)
      setStatus(`${plugin.name} added to this Stage.`)
      setSource('')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Plugin could not be imported') }
  }
  return <section className="rack-plugin-upload">
    <h2>Add your plugin</h2>
    <label>Plugin JSON file<input type="file" accept="application/json,.json" onChange={(event) => {
      const file = event.target.files?.[0]
      if (file) void file.text().then(install).catch(() => setStatus('Plugin file could not be read'))
      event.target.value = ''
    }} /></label>
    <label>Or paste plugin JSON<textarea value={source} onChange={(event) => setSource(event.target.value)} /></label>
    <button type="button" disabled={!source.trim()} onClick={() => install(source)}>Import plugin</button>
    <p role="status">{status}</p>
  </section>
}
