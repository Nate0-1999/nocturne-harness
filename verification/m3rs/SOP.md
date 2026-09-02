# M3RS verification SOP and trace

## Boundary

- Released source bases: Harness `8b1b046ef2931fd3c92890b4e0925d53f7591cbf`; Spine `950bc07c70e933a6a2a8b8f609d31d13066a2b36`.
- Disposable identity: `m3rs-sop-verification`.
- Disposable paths: `/tmp/nocturne-m3rs-home-rs02`, `/tmp/nocturne-m3rs-project-rs02`, `/tmp/nocturne-m3rs-project-b-rs02`.
- Both the Codex in-app browser and Chrome were used. All prompts, files, memories, and seeds were synthetic.
- No owner-memory write was permitted. A fixture-only curator walk was not redirected onto the shared owner corpus.

## Chronology

1. Ran the packaged heartbeat, full Spine suite, and full Harness suite before live work.
2. Claimed M3RS through the Garden mutex and pushed the claim.
3. Cloned clean released bases into `/tmp`, initialized a disposable Nocturne home, and ran ordinary `nocturne up --no-open` once from a fresh terminal.
4. Used a direct packaged daemon with the verification principal for write-bearing checks, because ordinary `up` stamps the local owner identity.
5. Walked all fifteen charge items in order. Each observed shortfall was frozen; no product file was edited.
6. Used a real OpenRouter model for synthetic chat/build/image prompts and the real Palace for the isolated verification identity.
7. Approved the page seed, denied the CLI seed, tombstoned the three approved/remembered memories, and denied all eight extraction candidates created by the failed Symphony attempts.
8. Verified cleanup with narrow live reads: zero active M3RS memories, empty verification queue, zero pending curator cards.
9. Ran `nocturne doctor` and one verified `nocturne backup` against the released remote Palace.
10. Re-ran exit suites from clean-base distributions in `/tmp`; the source worktrees remained untouched except for this verification directory.

## Important negative evidence

- First cold-start Rack: connected, but no version label.
- Project key versus filesystem location: separate concepts in the released app; no location badge.
- Symphony: the model produced a plausible plan/charters/budget, then the run became partial error and never yielded the required card.
- Wrong-folder write: the agent moved proactively, so the mandated refusal/remedy sequence was absent.
- Conversation: one run exposed raw reasoning/process JSON and a base64 screenshot payload.
- Memory near-miss list: empty, preventing add-back.
- Restart: thread IDs returned but their messages did not; restored entries were empty/not-loaded stubs.
- Deck: button fire worked after a countdown; Enter did not.
- Curators: no isolated messy fixture Palace was available, so the owner corpus was not used.

## Reproduction notes

- The released CLI seed endpoint is fixed to `127.0.0.1:8765`; the verification-principal packaged daemon was therefore run on that port for the CLI half of step 14.
- Chrome chooser upload timed out. The in-app browser clipboard path accepted the same synthetic JPEG and the switched model described it correctly.
- Browser screenshots are JPEG bytes and are named `.jpg`; an initial `.png` extension was corrected before hashing.
- The two pure-render captures share SHA-256 `c1b008217925ecdbd2c5352a0b6a02fb095d3bda12f76a06e1816f120e51fd6f`.
