# Changelog

## 0.1.30 - 2026-09-22

- The look pass: one right-sized, chamfered button style with matching selects
  and toggles in every module and theme; a short hover tip on every control;
  narrating sentences removed; one title style; denser threads and spend table.
  The memory gate: one heading over injected memories and two small buttons
  per card, × to remove and ×! to delete permanently behind a yes/no.
  Cards show score, name and memory; the relevance features are a spider-web
  chart on hover.
  Otherwise behavior is unchanged. Pair with Memory 0.1.30; the API contract
  is unchanged.

## 0.1.29 - 2026-09-22

- Protect the context window from oversized returns: one query or sub-agent
  return may take a share of the compaction limit (10% by default, 1–25% by the
  sender's choice). A query over its share arrives as an error with a brief
  head; a sub-agent over its share is told exactly how much to shorten, twice,
  then cut. The Security module shows shares, bounds, cuts and send-backs.
  Pair with Memory 0.1.29.

## 0.1.28 - 2026-09-16

- Keep Wizard Mode and Technomancer glyphs clear of module controls and use
  the Nocturne ouroboros-and-moon mark for the packaged favicon.
- Resolve all three CI Memory checkouts from the exact dependency version.

## 0.1.26 - 2026-09-16

- Correct Palace change triggers to query the principal's full memory graph.
  File, queue and Palace triggers now have real-provider acceptance evidence.
  Pair with Memory 0.1.26; the API contract remains 0.1.25.

## 0.1.25 - 2026-09-16

- Save and rerun named workflows, schedule them with cron or change triggers,
  and monitor their state, spend and exit checks in Jobs. Background shells
  persist across turns with explicit read and stop tools. Pair with Memory 0.1.25.

## 0.1.24 - 2026-09-16

- Keep normalized conversation history once after a failed turn and exclude
  earlier responses from new spend receipts. Pair with Memory 0.1.24.

## 0.1.22 - 2026-09-16

- Show when retraining is running while the current scorer keeps serving.

## 0.1.21 - 2026-09-16

- Pair with the Memory correction that logs reviewed injection decisions in the
  creation stream. Add the repeatable three-round build measurement runner.

## 0.1.20 - 2026-09-16

- Preserve deletion reasons and stack-selected scorer previews. Show the live
  learning registry, creation survival, curator axis provenance, project offsets
  and measured replay terrain; keep retrain results visible after polling.

## 0.1.19 - 2026-09-16

- Inspect versioned tools and skills from a thread, or turn workspace tools off
  in settings. Rewind chat and files from per-turn shadow checkpoints while
  retaining abandoned work. Update Pydantic AI to 2.43.0 and its harness to
  0.31.0, with cancellation-history repair in the Nocturne adapter.

## 0.1.18 - 2026-09-16

- Record cloud invoices from the owner's spend panel, with replay-safe billing
  and daily totals separate from broker reconciliation. Includes the 0.1.17
  compaction changes alongside the spend controls introduced in 0.1.16.

## 0.1.16 - 2026-09-16

- Explain retained model-policy choices. Show scoped spend rates, daily costs,
  broker reconciliation and cache reuse per message. Optional per-run and UTC-day
  spend walls pause ordinary runs when reported costs reach their limits.

## 0.1.15 - 2026-09-15

- Keep the Palace memory trace readable and scrollable when the scene and
  selected memory fill the module.

## 0.1.14 - 2026-09-15

- Show old memory bodies and confirmed near-miss add/pop-off controls in the
  Palace trace. Remember rejected candidate bodies, preserve thread locks,
  and confirm Palace deletion while retaining revision history.

## 0.1.13 - 2026-09-15

- Spend and Palace State use the daemon's principal. Only the configured owner
  can request the whole Palace; principal views omit shared database and broker
  totals. Update the app with this Palace release: older metrics requests without
  a principal are refused.

## 0.1.12 - 2026-09-15

- Publish as `nocturne-harness` with the matching `nocturne-memory==0.1.12`
  dependency; the `nocturne` command and Python imports stay the same.

- Replaced the downloaded PI/Node tool runtime with the in-process official
  `pydantic-ai-harness` filesystem, shell, and Skills capabilities while retaining
  NOCTURNE's location fence, movement refresh, journal, broker, and owner loop.
- Added context lines to the adopted grep path and model-visible access to each
  skill package's bundled resources through small NOCTURNE-owned shims.

## 0.1.5 - 2026-08-18

- Added optional append-only Palace backup and resurrection for conversation transcripts without
  weakening the mandatory local journal.
- Made memory relevance follow the agent's project-relative location while preserving the prior
  scorer exactly when location cannot be proved.
- Added run-scoped memory staging for multi-agent work: each attempt sees only its own drafts,
  unanimous winners enter the existing explicit-consent Palace queue, and losing drafts retain
  tombstoned lineage.
- Kept broker routing behind one adapter seam without changing existing OpenRouter behavior.

### Upgrade note

Remote Palace package version advances from `0.1.4` to `0.1.5` after a fresh verified backup.
Database schema advances from `0012` to `0015`; authenticated health advances API contract
`0.1.1` to `0.1.4` for transcript backup, location-aware scoring, and run-scoped memory staging.

## 0.1.4 - 2026-08-13

- Made exact duplicate saves reinforce the authoritative memory atomically, with plain guidance
  for near matches and conflicts instead of raw protocol details.
- Made memory edits and project selection visibly acknowledge daemon truth, including explicit
  no-change and rejected-binding explanations rather than silent success.
- Made provider refusals terminate streaming reliably and made pasted seed retries converge on one
  durable review batch instead of duplicating or losing work after a rolled-back response.
- Extended owner-surface honesty across memory scores, controls, loading states, and Palace health:
  human-sized numbers, owner language, and live readiness rather than implementation vocabulary.

### Upgrade note

Remote Palace package version advances from `0.1.3` to `0.1.4` after a fresh verified backup.
Database schema remains `0012`; authenticated health advances API contract `0.1.0` to `0.1.1`
for the authoritative duplicate-reinforcement behavior.

## 0.1.3 - 2026-08-12

- Added the Infinite Stage with persistent layers, pan and zoom, removable/recoverable modules,
  standardized drag/resize behavior, quieter chrome, and readable human-number projections.
- Added three persistent built-in themes plus the deterministic Plate Press, which turns an owner
  image into a validated, switchable, removable colorway without an LLM call.
- Made startup and deployment one lifecycle decision: unreleased source starts with a plain
  development-ground explanation instead of offering an update the immutable release guard will
  refuse, backed by an enumerated clean-room lifecycle matrix.
- Added the public API contract version to authenticated Palace health and a standing data-bearing
  UI canon for Stage mechanics, live controls, responsive collisions, and display precision.

### Upgrade note

Remote Palace package version advances from `0.1.2` to `0.1.3` after a fresh verified backup.
Database schema remains `0012`; authenticated health now declares API contract `0.1.0` separately
from package and storage versions.

## 0.1.2 - 2026-08-10

- Added durable single-image prompts with model-exact OpenRouter capability checks, restart-safe
  attachment history, and plain local refusals when image support cannot be proved.
- Added strict client support for atomic verification-only injection-event annotations and stamped
  future deployment verification with the canonical non-owner machine identity.
- Kept owner learning evidence honest by narrowly excluding recognized deployment-verification
  identities and providing guarded annotations without fabricating signals or rewriting history.

### Upgrade note

Remote Palace schema advances from `0011` to `0012` only after a verified backup. The three legacy
deployment-verification annotations remain a separate post-rollout data-plane operation.

## 0.1.1 - 2026-08-10

- Hardened local and remote Palace startup, health checks, backups, and guarded owner deployment
  flows through the `nocturne` command.
- Restored journaled threads after restart and added durable project context, guided semantic
  memory splitting, and in-page seed ingestion.
- Added an owner-visible learning path with progress, accuracy, generation scores, proposal
  audition, and explicit owner-only activation.
- Improved Vitals accuracy, narrow-screen Rack layouts, scorer simulation, and plain startup
  remedies while hardening release and credential boundaries.

### Upgrade note

Remote Palace schema advances from `0009` to `0011` only after a verified backup.
