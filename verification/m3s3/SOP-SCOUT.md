# M3S3 confirmation scout — ALIGNED items only

Date: 2026-08-21

Identity: `codex / 2026-08-21 / s321`

Surface: ordinary packaged owner app in real Chrome at `http://127.0.0.1:8893/`.
This was not a scenario or regression fixture. The runtime paired Harness
`43816ec` with current local Spine `3d8286d` because the current Harness expects
API contract `0.1.5` / schema `0016`, while the released Palace still reports the
older contract. No product change was made for this verification-only packet.

## ALIGNED — PASS: Recipe renders the real graph

WHAT I DID: In a fresh owner thread I sent `Take this to a Symphony.`, completed
the visible deliberation, signed its T2 wall, and held a three-step plan for
steering. I added Recipe from the Stage Library and inspected both the rendered
module and `GET /v1/rack/query?resource=recipe_graph&as_of=now`.

WHAT I EXPECTED: Recipe should render the signed plan's actual packet, step,
judge, blocking, and milestone data rather than a decorative or fixture graph.

WHAT I SAW: Packet `01M0K3JHVK0H0EJM3C2NW8V9GM`, revision 1, rendered three
inputs, their judge stages, sequential blocking joins, and the final milestone.
The first search step was running; its three judges and later packet steps were
blocked. Selecting the live cell exposed the same owner motivation, done-when,
step identity, and state returned by the endpoint. See
[01-recipe-running.png](01-recipe-running.png).

WHY IT MATTERS: The owner is looking at the real execution topology and can
reason about the current work from it.

## ALIGNED — PASS: completion grid follows live state

WHAT I DID: From the ordinary Deck I used `Finish surviving attempts`, then
returned to the same Recipe instance.

WHAT I EXPECTED: State changes should alter the graph's emphasis and milestone;
future/current styling must not remain frozen after completion.

WHAT I SAW: Recipe changed to `6 complete · 0 ready`; every step and judge cell
was passed and visually receded, and the milestone read `The whole plan is
complete.` See [02-recipe-completed.png](02-recipe-completed.png).

WHY IT MATTERS: Brightness and completion are trustworthy signals of live plan
state, not a static illustration.

## ALIGNED — PASS: one-click phone recovery is usable

WHAT I DID: At exactly 390 x 844 I recovered Recipe once from the visible
Off-screen rail, horizontally scrolled its native grid, reset the disposable
layout, then recovered The Deck once from the same rail and opened its settings.

WHAT I EXPECTED: One obvious click should return each whole instrument to a
readable, operable phone view.

WHAT I SAW: Recipe settled at `(28,122.4)`, `334 x 691.6`, wholly inside the
390 x 844 viewport. Its 916-pixel grid remained operable in a 310-pixel native
horizontal scroller; a real pointer scroll reached `scrollLeft=580` and exposed
the served milestone without moving the page. The Deck settled at `(0,135.4)`,
`334 x 691.6`, wholly inside the viewport, and its settings dialog opened.
See [03-phone-recipe-before.png](03-phone-recipe-before.png),
[04-phone-recipe-after.png](04-phone-recipe-after.png),
[05-phone-recipe-milestone.png](05-phone-recipe-milestone.png),
[06-phone-deck-before.png](06-phone-deck-before.png), and
[07-phone-deck-after.png](07-phone-deck-after.png).

WHY IT MATTERS: Recovery restores a working instrument, not merely a tiny or
clipped thumbnail.

## ALIGNED — PASS: project binding persists and sibling selects zero

WHAT I DID: I created project `m3s3-primary-s321`, recorded one real memory
through `/remember`, switched through the visible project control to
`m3s3-sibling-s321`, reloaded, and sent the sibling's first prompt. I stopped at
the review gate before any model continuation.

WHAT I EXPECTED: The selected project should survive reload, and the bound
sibling thread must receive no memory from the primary project.

WHAT I SAW: The transcript catalog durably bound thread
`5970ce07-78b0-43c5-8d2a-1ee1b0d2d2bc` to the primary project and thread
`611ee603-911e-4fc7-888b-4034c32cf565` to the sibling. Reload preserved the
sibling selection. Gate injection `590845b2-80ec-4573-9cf9-bbddbbb58171` used
`m3ti-thread-v1` and contained zero injected memories, zero near misses, and no
resolution error. The run was cancelled at the gate. See
[08-project-sibling-reload.png](08-project-sibling-reload.png) and
[09-project-sibling-zero.png](09-project-sibling-zero.png).

WHY IT MATTERS: The owner can change project context without cross-project
memory leakage, including on the first prompt in the sibling thread.

## Cleanup and result

The sole verification memory, `f21c2e51-6c37-4883-a483-c986e49973ba`, was
revision-written from active revision 1 to tombstoned revision 2. A final active
list returned zero. The isolated `n8_m3s3` database, container, volume, and
network were then removed. Browser console warning/error count was zero and the
viewport override was reset.

PASS: all four charged ALIGNED items passed. No DERIVED item was tested or
claimed, and no new finding was opened.
