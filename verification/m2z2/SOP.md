# M2Z2 — guided semantic split recovery SOP

Status: **EXECUTED / PASS** on 2026-08-09.

## Identity and ground

- Verification principal and machine: `m2z2-sop-verification`
- Owner app: `harness.daemon:create_dev_app` at `http://127.0.0.1:8792/`
- Structured provider: real OpenRouter `openai/gpt-4.1`
- Palace: current local Spine checkout with Postgres and real OpenRouter
  `openai/text-embedding-3-small` embeddings
- Source: `LIVE_SPLIT_SOURCE` in `tests/test_agent.py`

The historical M2X disposable home was removed during that scout's enacted
cleanup, and its committed report records the failure but not the original
paragraph. This recovery therefore used the exact durable three-claim source
checked into the M2Z2 regression, not a falsely reconstructed historical
paragraph.

## Procedure and observations

1. I transmitted the complete oversized `/remember` source through the real
   owner page. The source contains three unrelated durable claims, qualifiers
   that must not disappear, and operation-only framing that must remain in the
   exact coverage witness but must not become memories.
2. The first inherited prompt failed safely against real models. Diagnostics
   showed why: providers treated locally resolved references as unsafe, omitted
   operation-only coverage, emitted summary-length labels, or trimmed boundary
   spaces. The deterministic A-050 validator rejected every non-exact draft;
   no Palace write occurred.
3. Decision 049 tightened only the provider-facing instruction/schema: locally
   resolved references remain standalone; operation text and whitespace remain
   byte-exact in coverage; labels are short retrieval handles under the enacted
   ceiling. The validator, source authority, limits, and atomic Spine contract
   remain unchanged.
4. A direct real-provider diagnostic returned `VALID_CHILDREN 3` through the
   unchanged validator. I then repeated the same source through the owner page
   against the current local Spine checkout.
5. The page rendered:
   `Remembered 3 linked memories: 'Ledger silver cover purpose', 'Lantern
   storage and return', 'Weather card: north wind protocol'.`
6. Refreshing Memory showed exactly three active revision-1 facts. Their bodies
   retained the silver-cover/calibration-only/not-biography qualifier, the
   eastern-shelf/LANTERN-SEVEN/return/unrelated qualifier, and the north-wind/
   settle/destroy-at-verification qualifier respectively.
7. SQL traced source `cc709779-60f6-4b37-a438-f2ddeb5b0abf` as tombstoned from
   birth with reason `remember/source-split`. Children
   `42351467-8acb-4469-b599-835bc4e62cf9`,
   `b50a91d1-a052-4ff3-b97e-ae7410c4b8c8`, and
   `c6de4da5-8c1f-4c90-ac70-2b4de0e20d6e` each had revision 1 reason
   `remember/split-child` and the same source revision UID parent. The edge
   table contained all six directed `relates_to` sibling edges.
8. I tombstoned the three exact child IDs through PATCH `/v1/memories/{id}`.
   Each returned revision 2 and machine `m2z2-sop-verification`; the source was
   already tombstoned. I stopped the owner app and removed the temporary local
   containers while preserving the ordinary development volume.

## Verdict

PASS. One oversized, multi-claim `/remember` became three independently
retrievable, lossless children in one atomic linked family. No raw chunking,
summarization, truncation, partial family, owner signal, or production
infrastructure mutation occurred. The deployed 0.1.0 Palace correctly remained
untouched; `/v1/memory-splits` reaches it only through the separately governed
M2Z5 release.

## Unscripted finding

The nominal recovery premise said the pushed code was already gate-verified.
Real-provider replay disproved that premise: deterministic fixtures could not
show provider drift at the exact witness boundary. Refusing to close on green
unit tests found and fixed the last product-facing gap without weakening the
losslessness law.
