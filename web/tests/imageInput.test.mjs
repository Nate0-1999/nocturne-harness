import assert from 'node:assert/strict'
import test from 'node:test'

import {
  IMAGE_ACCEPT,
  ImageInputError,
  MAX_IMAGE_BYTES,
  formatImageBytes,
  prepareImage,
} from '../src/imageInput.ts'

/** A-052 and B.6 r12 require the browser entrance to emit the one canonical bounded image
 * shape and reject a lying file before it enters the durable daemon pipeline.
 */
test('image preparation validates signature and emits canonical input plus compact view', async () => {
  const bytes = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
  const prepared = await prepareImage(new File([bytes], 'witness.png', { type: 'image/png' }))

  assert.equal(IMAGE_ACCEPT, 'image/png,image/jpeg,image/webp,image/gif')
  assert.deepEqual(prepared.input, {
    kind: 'image',
    media_type: 'image/png',
    data_base64: 'iVBORw0KGgo=',
  })
  assert.equal(prepared.view.kind, 'image')
  assert.equal(prepared.view.media_type, 'image/png')
  assert.equal(prepared.view.byte_count, bytes.byteLength)
  assert.match(prepared.view.sha256, /^[0-9a-f]{64}$/u)
  assert.equal(prepared.local_filename, 'witness.png')
  assert.equal(prepared.data_url, 'data:image/png;base64,iVBORw0KGgo=')
})

/** A-052 and B.6 r12 require a plain local remedy for unsupported, empty, oversized, or
 * signature-mismatched files instead of sending provider-shaped ambiguity.
 */
test('image preparation rejects every local invalidity with a usable remedy', async () => {
  const cases = [
    [new File(['svg'], 'vector.svg', { type: 'image/svg+xml' }), /PNG, JPEG, WebP, or GIF/u],
    [new File([], 'empty.png', { type: 'image/png' }), /non-empty/u],
    [
      new File([new Uint8Array(MAX_IMAGE_BYTES + 1)], 'large.png', { type: 'image/png' }),
      /no larger than 5 MiB/u,
    ],
    [new File(['not png'], 'lying.png', { type: 'image/png' }), /does not match/u],
  ]
  for (const [file, remedy] of cases) {
    await assert.rejects(() => prepareImage(file), (error) => {
      assert.ok(error instanceof ImageInputError)
      assert.match(error.message, remedy)
      return true
    })
  }
  assert.equal(formatImageBytes(8), '8 B')
  assert.equal(formatImageBytes(1536), '1.5 KiB')
  assert.equal(formatImageBytes(2 * 1024 * 1024), '2.0 MiB')
})
