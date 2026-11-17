import { useState } from 'react'
import { parseRackPlugin, saveRackPlugin, type CustomRackModuleId } from './rackPlugins'
import { registerRackPlugin } from './rack'
import { registerStagePlugin } from './stageLayout'
import { Button, FileField, TextArea } from './kit'
import { failureMessage } from './requestFailure'

/** FL-105: import one self-contained plugin through the shared rack contract. */
export function RackPluginUpload({ onInstalled }: { onInstalled: (id: CustomRackModuleId) => void }) {
  const [source, setSource] = useState('')
  const [status, setStatus] = useState('')
  function install(text: string) {
    try {
      const plugin = parseRackPlugin(JSON.parse(text))
      saveRackPlugin(plugin)
      registerRackPlugin(plugin)
      registerStagePlugin(plugin.id)
      onInstalled(plugin.id)
      setStatus(`${plugin.name} added to this Stage.`)
      setSource('')
    } catch (error) { setStatus(failureMessage(error, 'The plugin was not imported. Choose a valid plugin JSON file.')) }
  }
  return <section className="rack-plugin-upload">
    <h2>Add your plugin</h2>
    <label className="kit-label">Plugin JSON file<FileField data-tooltip-detail="Choose a self-contained plugin bundle from this machine." accept="application/json,.json" onChange={(event) => {
      const file = event.target.files?.[0]
      if (file) void file.text().then(install).catch(() => setStatus('The plugin file could not be read. Choose it again.'))
      event.target.value = ''
    }} /></label>
    <label>Or paste plugin JSON<TextArea data-tooltip-detail="Paste a plugin bundle instead of choosing a file." value={source} onChange={(event) => setSource(event.target.value)} /></label>
    <Button action="import" variant="primary" type="button" data-tooltip-detail="Add the pasted plugin to this stage." disabled={!source.trim()} onClick={() => install(source)}>Import plugin</Button>
    <p role="status">{status}</p>
  </section>
}
