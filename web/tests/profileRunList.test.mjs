import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** A-103 / M8PA: a poll can list a background job first while the owner works in another conversation. */
test('ProfileRunList renders the open conversation first and keeps the remaining order', async () => {
  const vite = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  try {
    const { ProfileRunList } = await vite.ssrLoadModule('/src/ProfileRunList.tsx')
    const runs = ['workflow', 'background', 'open'].map(id => ({ run_id: id, thread_id: id, name: id }))
    function buttons(current) {
      const html = renderToStaticMarkup(createElement(ProfileRunList, { runs, current, onOpen() {} }))
      return Array.from(html.matchAll(/data-run-id="([^"]+)"/gu), match => match[1])
    }
    assert.deepEqual(buttons('open'), ['open', 'workflow', 'background'])
    assert.deepEqual(buttons('idle'), ['workflow', 'background', 'open'])
  } finally {
    await vite.close()
  }
})
