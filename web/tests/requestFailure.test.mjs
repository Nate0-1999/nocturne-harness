import assert from 'node:assert/strict'
import test from 'node:test'
import { failureMessage, responseFailure, serverMessage } from '../src/requestFailure.ts'

/** SD-096 rule (e): a broken network or unexpected server response cannot expose diagnostics. */
test('request failures hide exceptions, status text and structured diagnostics', async () => {
  const next = 'The document could not be read. Keep the file and upload it again.'
  for (const detail of ['Rack action failed (503)', { code: 'internal_error' },
    'RuntimeError: database password rejected.', 'An unexpected database secret was exposed.']) {
    const error = await responseFailure(new Response(JSON.stringify({ detail }), { status: 503 }))
    assert.equal(failureMessage(error, next), next)
  }
  assert.equal(failureMessage(new TypeError('Failed to fetch'), next), next)
  assert.equal(failureMessage(new SyntaxError('Unexpected token in JSON'), next), next)
})

/** F219/M8LC: already-authored guidance survives the request boundary verbatim. */
test('an authored refusal and its next step stay as written', async () => {
  const sentence = 'Nothing changed. Edit the memory body before saving.'
  const error = await responseFailure(new Response(JSON.stringify({ detail: sentence }), { status: 409 }))
  assert.equal(failureMessage(error, 'The edit was not saved. Try again.'), sentence)
  assert.equal(serverMessage('The Palace is still busy. Try again shortly.', 'Try again.'),
    'The Palace is still busy. Try again shortly.')
})

/** FL-018: a later spend warning must not erase the memory-degraded notice. */
test('the local-copy clock and a joined authored notice retain their wording', () => {
  const sentence = 'The Palace is unreachable; memory is from the local copy, as of 18:30. The Palace is still busy. Try again shortly.'
  assert.equal(serverMessage(sentence, 'The request failed. Try again.'), sentence)
})
