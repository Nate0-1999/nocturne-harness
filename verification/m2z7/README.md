# M2Z7 evidence

One real owner-path proof for A-052 image input. The current Harness daemon,
current built SPA, production Spine 0.1.1, and real OpenRouter routes ran under
the isolated identity `m2z7-sop-verification`; no presentation fixture supplied
an answer.

The primary result is deliberately small:

- The owner path pasted `visual-witness.jpg` into the chat composer. The
  recorded trace carries the non-leading prompt and exact response:
  `openrouter:google/gemini-2.5-flash-lite` answered `47 amber moths` /
  `Northwest` in one provider request.
- The exact JPEG survived daemon restart. The journal-backed message URL
  returned byte-for-byte the checked-in witness with its SHA-256 as ETag.
- A second thread selected the catalog-declared text-only route
  `openrouter:deepseek/deepseek-v4-flash-0731`. Harness refused locally, named
  the model and `/model` remedy, wrote a durable completed turn, and recorded
  zero provider requests/tokens. That refusal also survived restart.
- Desktop and 390×844 views remained usable. The mobile chat document measured
  `390 / 390` client/scroll width and the image remove target measured
  `52.52 × 44` CSS pixels. Browser warnings/errors were empty.

`trace-summary.json` is the machine-readable observation record. `SOP.md`
records the exact bounded journey and cleanup. `SHA256SUMS` freezes the retained
packet. The two private JSONL journals were hashed into the trace and then
removed with the validated disposable home; raw attachment base64 and provider
credentials are intentionally not retained here.

Artifacts:

- `source-card.html` / `visual-witness.jpg` — deterministic, nonsecret visual
  witness and its rendering.
- `01-paste-preview.jpg` — actual clipboard-paste preview before transmission.
- `02-real-openrouter-answer.jpg` — real Gemini visual answer.
- `03-restart-hydrated.jpg` — the rehydrated answer after restart; exact image
  rehydration and byte retrieval are recorded in `trace-summary.json`.
- `04-text-only-refusal.jpg` — the visible tail and resend remedy of the local
  unsupported-model refusal; its exact full text is frozen in the trace.
- `05-mobile-refusal.jpg` — the refused image turn and controls at 390×844;
  exact refusal text is frozen in `trace-summary.json`.
- `06-mobile-image-preview.jpg` — mobile preview and 44 px remove target.
- `07-positive-vitals.jpg` — thread-current `$0.000219800000` provider receipt.

See `SOP.md` for reproduction and `trace-summary.json` for exact IDs, counts,
digests, and non-residue claims.
