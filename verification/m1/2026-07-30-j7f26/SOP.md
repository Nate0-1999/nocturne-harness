# J3–J8 independent browser record

Session: `codex / 2026-07-30 / 7f26`

I drove the built Harness SPA through the in-app browser. Product actions used
visible controls; fixture setup, deliberate service death, conflict staging,
and exact-ID cleanup used bounded local controls. I visually inspected every
image cited below.

## J3 — gate, end to end

Result: **PASS**

On fresh thread `3ec5bb39-b539-48c8-8b6c-339ca9441422`, the first prompt
stopped before the model and displayed injection
`bea3335c-76f3-4e28-9f6f-506a7dd8688f`, scorer `v0`, full bodies, six raw
features per card, and a near miss.

I kept one card, removed one as not relevant, removed the false card as wrong,
removed the junk card as never, and added the near miss. I observed the second
hard pause for wrong-memory resolution, edited the false body, and only then
allowed the deterministic model to run. The second chat prompt skipped the
first-turn gate.

Images: `08`–`12`. Trace: `j3-h5-trace.jsonl`.

The persisted event rows use the same on-screen injection ID. The committed
block contains only `H5 proof — keep` and `H5 proof — add back`; all removed
cards are absent.

## J4 — quarantine

Result: **PASS**

I opened three fresh threads and used the scoped modifier menu to mark the
same memory, `222b10dc-c88e-424e-8beb-5299f96bd9df`, as Never each time.
Images `20`, `21`, and `22` visibly show the menu on each distinct injection.

After the third commit, read-only SQL showed:

```text
status=quarantined
never_kills=3
removals=3
bias=-0.45000002
revision=8
```

The fourth fresh gate had three selected cards and one near miss; the junk
memory was absent from both the screenshot and traced prepare result.

Image: `23`. Trace: `j4-quarantine-trace.jsonl`.

## J5 — human hands

Result: **PASS**

I completed the H6 panel path on desktop and again at exact 390×844:

- removed an injected unit from the open thread while it remained Stored;
- saved a body edit through CAS;
- persisted a pin toggle without rewriting current context;
- staged a concurrent edit and clicked Save once;
- observed revision 2, the current winner, the preserved user draft, and
  explicit Retry Save; I did not retry;
- sent a second prompt and saw the frozen context retain/removed/new-pin
  distinctions.

Images: `24`–`34`. Traces: `j5-h6-desktop-trace.jsonl` and
`j5-h6-mobile-trace.jsonl`.

The desktop edit trace records `editor=user`, `reason=panel/edit`, expected
revision 3, and returned revision 4. A read-only join to the head revision
confirmed a non-null parent. The conflict trace records stale expected
revision 1, current revision 2, and no retry.

At 390×844 I also ran `/remember`, observed the confirmation and panel row,
then completed the H8 Markdown/sanitization walk. Layout inspection measured
`scrollWidth=clientWidth=390`, minimum visible action height 44px, zero raw
sentinel buttons/scripts, an undefined script sentinel, literal plain user
markup, and one rendered table/code surface.

Images: `35`–`38`. Trace: `j5-h8-trace.jsonl`.

## J6 — replay

Result: **PASS**

See `j6-replay.md`.

## J7 — memory death

Result: **PASS**

With the isolated Spine container stopped, Memory Refresh surfaced
`The memory service is unavailable. Try again.` The same open thread accepted
another prompt and returned its next deterministic response. A fresh thread
then proceeded memoryless with the visible warning
`Memory is unavailable; continuing without injected context.`

After Spine restarted, the next fresh thread opened a normal scored gate.

Images: `16`–`19`. Trace: `j7-memory-death-trace.jsonl`. The trace contains a
prepare call with no result followed by a model call, which is the intended
fail-open ordering. The fixture process produced no traceback or crash.

## J8 — mobile

Result: **PASS**

At exact 390×844, the J3 gate used a readable one-column layout with full
bodies and six score bars. The page measured `scrollWidth=clientWidth=390`;
visible gate actions were at least 44px high. I removed one selected card with
one tap, added the near miss with one tap, continued, and used the chat
composer after the response.

Images: `13`–`15`. Trace: `j8-h5-mobile-trace.jsonl`.

## Additional packet SOP rewalks

The H4 phone path preserved an active turn plus one queued prompt across
reload, began the queued turn only after the first completed, and preserved
partial output after Stop. Images `39`–`41`; trace `h4-mobile-trace.jsonl`.

H5, H6, and H8 trace assertions passed. Every fixture set was cleaned by exact
ID. The browser viewport override was reset.
