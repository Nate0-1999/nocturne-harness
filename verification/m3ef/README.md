# M3EF exact-fence verification

This proof uses the real owner Rack and the configured OpenRouter model. It is
not the deterministic scenario app and does not use a fixture model.

## Real move-then-act walk

- Identity: principal `m3ef-verification-20260828-ef28`, machine
  `m3ef-browser-verification`, agent `m3ef-owner-agent`.
- Model: `openrouter:minimax/minimax-m3`.
- Thread: `38649a11-fe5c-42c2-a9f0-e574c2c6fc18`.
- Run: `01M14DARETW165JK1EMHG8GV85`.
- Disposable workspace began at its root with `src/deep/proof.txt` containing
  `before`.

The owner prompt required the agent to try the nested edit before moving. The
durable tool trace records this exact order:

1. `edit` on `src/deep/proof.txt` refused before action with
   `Modification requires presence in the file's directory. Move to
   .../workspace/src/deep first.`
2. `move` to `src/deep` succeeded.
3. `edit` on the now-local `proof.txt` succeeded with short hash
   `7b9a72466d39`.
4. `read` returned one line, `after`, with the same hash.

The independent disk SHA-256 after the walk was
`7b9a72466d3960eb2aacccfc848939453490db0678bd4725def3f789b891c919`.
The toolset contract test also asserts that this successful move emits exactly
one `cwd_change` presence event before the successful edit/write events; refused
modifications emit no write event.

Memory prepare against the configured Palace failed open for this disposable
verification identity. The visible Rack named that condition and the real
OpenRouter turn continued without injected context; it does not weaken the
file-tool proof.

## Captures

- `01-real-agent-outcome.png` — the rendered owner prompt and final explanation.
- `02-real-tool-trace.png` — the rendered tool trace at the exact refusal result.

The machine-readable identities, timestamps, tool order, and capture digests
are in `trace-summary.json`.
