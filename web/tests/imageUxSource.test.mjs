import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** A-052 and B.6 r12 require one focused, accessible image entrance whose compact user view
 * survives Sending, FIFO queueing, and authoritative snapshot replacement on a narrow rack.
 */
test('composer image UX is focus-scoped, accessible, reconnectable, and responsive', async () => {
  const [app, protocol, store, bridge, shell, rack] = await Promise.all([
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/protocol.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/store.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/rackBridge.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/assets/shell.css', import.meta.url), 'utf8'),
    readFile(new URL('../src/assets/rack.css', import.meta.url), 'utf8'),
  ])

  assert.match(app, /onPaste=\{onComposerPaste\}/u)
  assert.doesNotMatch(app, /addEventListener\(['"]paste/u)
  assert.match(app, /data-testid="image-input"[\s\S]*?tabIndex=\{-1\}[\s\S]*?aria-hidden="true"/u)
  assert.match(app, /data-testid="attach-image"[\s\S]*?aria-describedby="composer-image-status"/u)
  assert.match(app, /aria-label=\{`Remove \$\{pendingImage\.local_filename\}`\}/u)
  assert.match(app, /aria-live="polite"/u)
  assert.match(app, /event\.currentTarget\.value = ''/u)
  assert.match(app, /<ChatModule key=\{snapshot\.selectedThreadId/u)
  assert.match(app, /journalImageSource\(threadId, messageId\)/u)
  assert.match(
    app,
    /`\/v1\/threads\/\$\{encodeURIComponent\(threadId\)\}\/messages\/\$\{encodeURIComponent\(messageId\)\}\/image`/u,
  )
  assert.match(app, /src=\{pendingImage\.data_url\}/u)
  assert.match(app, /className=\{image\.media_type === 'image\/gif' \? 'image-thumbnail--gif' : undefined\}/u)
  assert.doesNotMatch(app, /source === undefined \|\| image\.media_type === 'image\/gif' \|\| failed/u)

  assert.match(protocol, /'prompt\.submit': \{[\s\S]*?image\?: PromptImage[\s\S]*?symphony\?: SymphonyLaunch[\s\S]*?\}/u)
  assert.match(protocol, /function parseImageAttachmentView/u)
  assert.match(store, /image_preview_data_url: image\.image_preview_data_url/u)
  assert.match(store, /image: payload\.image \?\? outbound\.image_view/u)
  assert.match(store, /outboundPrompts: previous\.outboundPrompts\.filter/u)
  assert.match(app, /image_preview_data_url: outbound\.image_preview_data_url/u)
  assert.match(app, /'image_preview_data_url' in message/u)
  assert.equal((bridge.match(/rackSnapshotForIframe\(api\.events\.getSnapshot\(\)\)/gu) ?? []).length, 2)

  assert.match(shell, /\.composer-attachment__remove,\s*\.composer__attach\s*\{[^}]*min-height:\s*2\.75rem/su)
  assert.match(shell, /\.composer-attachment__meta\s*\{[^}]*min-width:\s*0/su)
  assert.match(shell, /\.message-image img,\s*\.image-tile--message\s*\{[^}]*max-height:\s*40dvh/su)
  assert.match(shell, /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.image-thumbnail--gif\s*\{[^}]*display:\s*none/su)
  assert.match(shell, /\.image-tile\.image-tile--gif-reduced\s*\{[^}]*display:\s*grid/su)
  assert.match(rack, /\.composer__attach:focus-visible/u)
})
