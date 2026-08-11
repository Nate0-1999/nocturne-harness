# Changelog

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
