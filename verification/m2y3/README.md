# M2Y3 verification

M2Y3 closes one false-failure disease at the owner API. When Spine has already
made queue work durable but the local request reports failure, Harness now
queries the authoritative pending queue and returns success only when the
caller identity and durable payload prove that exact work exists. A missing or
mismatched durable result still raises the original error.

## Real owner-path proof

The production owner app ran from the editable checkout against the configured
remote Palace with an isolated `NOCTURNE_HOME` and real OpenRouter routing. The
in-app browser completed a first-turn memory gate without changing its proposed
context, received a real `openrouter:minimax/minimax-m3` answer, clicked the
rendered **Archive** control, and observed the Thread Review surface open. The
first low-entropy thread folded out as a duplicate and correctly rendered
**Nothing pending**.

The acceptance probes then used synthetic, isolated identities through the same
owner API:

- Seed batch `c7e40000-0000-4000-8000-000000000002`: first submit returned 200
  in 33.76s with one pending card. The byte-identical replay returned 200 in
  0.32s with the same item UID and no second model split.
- Archive thread `c7e40000-0000-4000-8000-000000000003`: the first archive
  reproduced the slow partial-write path, taking 61.77s, yet reconciliation
  returned 200 with one pending card. The exact replay returned 200 in 0.15s,
  returned the same item UID, and reported `already_extracted=true`.
- Both verification candidates were explicitly denied as human verification
  data. Pending queue depth returned from three to three; neither verification
  item remained pending. No memory was accepted.

The rendered outcomes were asserted from the live accessibility tree. No
screenshot is retained because the full rack also rendered private owner memory
content; the machine-readable, privacy-safe observations are in
`live-reconciliation-summary.json`.

## Automated proof

- Focused Python reconciliation tests: 9 passed.
- Full Harness ground: 681 passed, 3 deselected.
- Test-motivation audit: 401 tests, 0 grandfathered.
- Web unit tests: 10 passed; ESLint and the production build passed.
- The adversarial tests prove mismatched batch digests and mismatched thread
  candidates remain loud. The web action-boundary tests prove asynchronous
  failures reach the owner-visible transport error while successful
  reconciliation stays quiet.

