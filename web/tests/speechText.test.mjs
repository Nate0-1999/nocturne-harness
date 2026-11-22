import assert from 'node:assert/strict'
import test from 'node:test'
import { speechSentences } from '../src/speechText.ts'

/** P1.2 / SD-106: a model's GFM tables and code must not reach the speech engine verbatim. */
test('the listener hears prose, link labels and one note per code block or table', () => {
  const source = '# **Welcome.**\n\nVisit [the library](https://example.com).\n\n~~~js\nprivateCode()\n~~~\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nGoodbye.'
  assert.deepEqual(speechSentences(source, true), ['Welcome.', 'Visit the library.', 'Code block skipped.', 'Table skipped.', 'Goodbye.'])
})

/** P1.2 / SD-106: network chunks can split decimals, sentence endings and Markdown tables. */
test('streaming commits whole sentences once and flushes the unfinished tail on completion', () => {
  const source = 'First sentence. It costs 2.50 dollars! Does it help? Last fragment'
  const expected = ['First sentence.', 'It costs 2.50 dollars!', 'Does it help?', 'Last fragment']
  let previous = []
  for (let end = 0; end <= source.length; end++) {
    const ready = speechSentences(source.slice(0, end), false)
    assert.deepEqual(ready, expected.slice(0, ready.length))
    assert.deepEqual(ready.slice(0, previous.length), previous)
    previous = ready
  }
  assert.deepEqual(previous, expected.slice(0, -1))
  assert.deepEqual(speechSentences(source, true), expected)
  assert.deepEqual(speechSentences('| Heading. More | Units |', false), [])
})
