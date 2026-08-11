# M2ZB real provider ceiling proof

This packet records one isolated owner-app path against the real OpenRouter route
`openrouter:rekaai/reka-edge`. It is not a fixture and it does not lower the model's advertised
16,384-token context window.

The run used the verification-only principal, machine, and agent ID
`m2zb-sop-verification`, a private disposable `NOCTURNE_HOME`, and a fresh local origin. Model
Device set `max_tokens=8`. Three synthetic, explicitly non-durable padding turns produced:

- a successful 6,079-input-token response;
- a successful 11,790-input-token response, which became the last trustworthy Context Bars
  observation; and
- one real provider request refused at 18,072 input tokens with HTTP 400 and the provider's
  16,384-token maximum-context message.

The current owner surface then showed `Context limit reached` and the plain remedy:
`This thread has reached rekaai/reka-edge's context limit. Archive it, then continue in a fresh
thread.` Context Bars remained `11.8K / 16.4K`; the zero-usage error chunk did not replace it with
`0 / 16.4K`. Reloading the thread preserved the same terminal voice and measurement.

`01-real-context-limit.jpg` is the post-reload current UI. `trace-summary.json` carries the exact
typed terminal payload and bounded usage facts without retaining the large synthetic prompts or
any credential material.

No retry, compaction, archive, memory tool call, durable memory, activation, deploy, or cloud
mutation occurred. The normal memory gate admitted zero memories. Remote injection and spend
records under the verification identity are expected append-only residue; the disposable local
home and listener were removed after the trace was frozen.
