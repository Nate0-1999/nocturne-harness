# M2Y5 SOP — in-page and command-line seed entrances

## Live environment

Real owner Harness on `127.0.0.1:8765`, configured owner Palace, and real
OpenRouter splitter/verdict calls. Verification data remained candidate-only
in the explicit seed review queue.

## Walkthrough

1. I opened the Palace queue from the running rack. I saw one plainly bounded
   target reading “Drop, paste, or choose Markdown”; the existing file choice
   remains present without being the only entrance.
2. I focused that target and pasted a short Markdown document. The surface
   changed to Working, then “Split complete.” Two memory candidates rendered
   together under one pasted document with Reject batch and Approve batch.
   Neither entered active memory.
3. I ran `nocturne seed verification/m2y5/cli-seed.md`. The command reported
   one memory waiting for review. After a clean rack reload, the pasted batch
   and CLI batch rendered together in the same Palace queue.
4. I executed `drop_check.mjs` against the same real app. It constructed a
   browser `File`, dispatched the real drop gesture onto the visible target,
   waited through the real splitter calls, and observed `dropped-seed.md`
   waiting for explicit batch review.
5. Adversarially, the CLI regression supplied a `.txt` file and proved the
   daemon was never contacted; the owner receives the plain Markdown remedy.

## Observation and friction

The three entrances converge cleanly and consent remains obvious. Closing and
immediately reopening the queue once showed an empty state while the API still
held all pending cards; a clean page reload reconciled them. This appears to be
an existing rack iframe remount/bridge race rather than ingestion data loss,
but it is real UI friction and should be carried to the gate rather than hidden.

Evidence: `paste-and-cli.png`; `drop_check.mjs`; CLI and seed unit tests.
