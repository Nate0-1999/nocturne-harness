# M3DK real-browser verification

This bundle records the bounded, verification-identity exit walk for the finished Deck.
It is a findings trace, not a fixture. The app ran from this source checkout with its
configured real OpenRouter model and a disposable `NOCTURNE_HOME`.

## Identity and ground

- principal: `m3dk-verification-20260828-dk27`
- machine: `m3dk-browser-verification`
- agent: `m3dk-owner-agent`
- model shown by the real Rack: `openrouter:minimax/minimax-m3`
- browser: the in-app Chrome browser at `http://127.0.0.1:58191/`
- captured: 2026-08-28 14:27–14:29 UTC

The first Alpha turn returned visible text `Alpha is ready.` and the same paid turn
emitted proposal `Approve Alpha.`. The first Beta turn returned a second proposal,
`Approve Beta`, after its empty first-turn memory review was explicitly continued.
The Deck showed two cards in server-time FIFO order: Alpha was `LONGEST WAITING`, Beta
was `WAITING`.

## Browser walk

1. The Deck queue measured 429 CSS px high and 580 CSS px scroll height. A real wheel
   gesture moved its nested `scrollTop` from 0 to 151 while the first card retained
   `data-primary="true"`; browsing did not reorder the queue.
2. Alpha's prefilled composer was changed from `Approve Alpha.` to
   `Approve Alpha after the browser walk.`. Pressing Enter immediately removed Alpha,
   promoted Beta to `LONGEST WAITING`, and exposed the six-second Undo control before
   the prompt was sent.
3. After the grace expired, the Rack reported the Alpha reply fired. The append-only
   transcript record linked source proposal run `01M14C9JCCKEKS1YAR7B889B5Z` to fired
   run `01M14CC1271SKC2JCK9TKHWJ7T`, preserved both exact texts, recorded character edit
   distance 23, and named provenance `owner_authored_with_assist`.
4. Beta's prefilled composer was fired and Undo was activated inside the same grace
   window. The Deck restored Beta as `LONGEST WAITING`, retained exact draft
   `Approve Beta`, and reported that nothing had been sent. No Beta fire record exists
   in its journal.
5. The fired Alpha turn completed normally and produced its next same-turn proposal.
   The resulting queue placed the still-older Beta card before that new Alpha card.
6. The app and Rack were cold-reloaded with Alpha selected. The thread list showed Beta
   as `NOT LOADED`, yet the journal-derived catalog restored both outstanding cards and
   kept the older Beta card first. This proves global means all conversations, not only
   snapshots visited during the current page lifetime.

The browser screenshots were inspected live through the browser control surface. They
are deliberately not committed: this packet's durable evidence is the source-owned
journal trace below plus the reproducible DOM measurements and automated contracts.

See `trace-summary.json` for the bounded identifiers and exact journal fact.
