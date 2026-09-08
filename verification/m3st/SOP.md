# Remember, queue ownership, and conversation drafts

PRECEDENT: PLAN M3ST; F075/F076/F077; ancestors M3VI, M3RL, M3CP.
The memory command must complete on the default model, refusals must explain
ownership, and changing Conversation mode must not erase unfinished text.

## Procedure

Use the real packaged app at the fresh 51945 origin and
`NOCTURNE_HOME=/tmp/m3st-verification/home`. Check `/v1/identity` for that
home and its distinct verification principal before capturing anything.

1. Create a thread in a disposable folder. On minimax, remember a short
   verification fact. Inspect the saved memory, then ask for it, inspect the
   gate, Continue, and read the answer. Capture save, gate, and recall.
2. Switch to gpt-4.1-mini with `/model`, remember a different verification
   fact, and capture its successful save.
3. Type an unsent draft. Switch Focused → Stack → Focused, inspect its exact
   text, and repeat at phone width. Explore thread switching and draft clearing
   after send without reloading.
4. Create a queue card under the first disposable principal. Load it in the
   browser, stop that daemon, and start the second disposable identity at the
   same temporary origin. Without reloading the stale card, reject its batch.
   Also attempt both decision routes directly, then prove the owning queue is
   still pending. This controlled identity switch is an adversarial test.
5. Tombstone the exact disposable memories, reject remaining disposable queue
   cards under their owning principal, verify cleanup, and stop this server.

## Execution

2026-09-08: PASS against the real Palace and OpenRouter using the built SPA and
`harness.packaged:create_app`, not an installed-wheel certification. Identity
receipts name both fresh homes/principals. Only disposable contents were sent.

| Action | Observed evidence |
| --- | --- |
| Minimax `/remember` | Saved lighthouse fact; `01-minimax-memory-saved.png` |
| Recall through gate | Same memory selected; Continue returned violet, twice, noon; `02` and `03` |
| gpt-4.1-mini `/remember` | Saved observatory key fact; `04-gpt-4-1-mini-memory-saved.png` |
| Focused → Stack → Focused | Exact unsent text retained; `05` and `06` |
| Explore another thread | Separate draft, original restored on return; `07` |
| Repeat at 390 × 844 | Draft retained at Stage zoom 34%; `08` (functional, not an ergonomics claim) |
| Send, then mode round-trip | Reply completed and composer stayed empty; `09` |
| Foreign stale-card rejection | Plain ownership refusal, HTTP 403; `10` and `11`; exact item/batch responses in `foreign-queue-refusals.json` |
| Cleanup | Owner of disposable card rejected it; two saved memories tombstoned; both verifier scopes have zero active memories/pending cards; `walk-cleanup.json`; second verifier queue clear in `12` |

Both live metadata saves used one request. The deterministic invalid-metadata
regression proves the legitimate second request and fails on old code; the walk
does not claim to have forced a live model retry. `memory-loop.json` preserves
usage, gate, and completion events; `journal-summary.json` has ten final messages
in the disposable project thread and zero in the automatically opened root thread.

The first real foreign rejection exposed a second message-swallowing catch in
Memory Ingest. After repairing the existing catches, repeated the same real
card/identity switch and captured `11`. No mocked response is used in this gallery.
The separate curator browser regression uses an explicitly injected 403 and then
proves normal denial still works. It is outside the full UI canon.

Contract tests use their existing generated principals, independently of the
walk. `contract-cleanup.json` records eight cleanup tombstones across boot/exit
runs; the contracts also tombstoned their two original CAS fixtures themselves.
Boot IDs were recovered from exact synthetic bodies, principal patterns and the
recorded test interval; exit IDs were recorded at creation. No tracked active
contract memory remains. Curator history is retained: two admissions, no run,
no pending card. No hard deletion or owner-home cleanup was performed.
