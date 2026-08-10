# M2XS delta re-scout

This is a real owner-path scout against the released remote Palace. It is not
an H5 presentation fixture and does not relabel M2Z4's disposable proposal as
owner data. The app ran from `harness.daemon:create_dev_app` at isolated origin
`127.0.0.1:8796`, with a disposable Nocturne home and explicit principal and
machine `m2x-sop-verification`. The checked-in product factory, current SPA,
OpenRouter models, Spine 0.1.1, and production schema 0011 were used.

The machine-readable record is `trace-summary.json`. The retained screenshots
use ordinals 01-15. Ordinal 05 was a blank capture and was discarded; ordinal
12 was an aborted duplicate of the scope-switch proof already retained in
09-11. No claim depends on either missing ordinal.

## Verdict

Items 17, 22, 51, 52, and 59 pass. Items 2-3 remain passed by M2Z5 report
088. Item 28 is absent because M2Z7 has not landed, exactly as its checklist
line permits.

Item 29 fails under F035. The daemon journal, saved memory, injection feature,
and CURRENT Graph/Injection results consistently name authoritative project
`build-test`, but the owner-visible Project control showed `m2xs-build-test`
in captures 04 and 07 before showing `build-test` in capture 11 for the same
restored thread shown in 07. The backend isolation proof for item 22 therefore
stands,
but the owner surface did not consistently show the binding that controlled
CURRENT scope. The retained evidence does not prove why, so this packet does
not invent a root cause.

Items 39, 42, 47, 48, and 49 do not pass. Production advertises four authentic
signals, three right, one wrong, and 75% agreement. Exact event/revision
correlation shows that three of those four points are D1/M2T/M2Z5 verification
artifacts. The authentic replay is one signal, zero right, one wrong, and 0%.
There is no measured generation and no proposal to audition. F033 carries the
smallest repair; M2Z4's connected disposable proof remains valid mechanics
evidence but is not substituted for an owner-Palace ratification.

Item 60 also fails. A real 16,384-token Reka Edge route, with thread-local
`max_tokens=8`, completed one 11,644-input-token request while Context Bars
showed 11.6K/16.4K and compaction off. The next bounded continuation produced
`run.done(partial=true, stop_reason=error)`, the owner saw only
`Run error · partial kept`, and Context Bars reset to 0. The UI and journal did
not identify a context-length rejection or offer archive-and-continue. The
scout stopped after that first refusal; F034 records the missing plain refusal
and measurement behavior without pulling M3 compaction into M2.

## Owner journey

1. Opened Vitals GLOBAL and Injection GLOBAL before creating verification
   traffic. Preserved the 4/25 baseline, the contaminated live sawtooth, the
   absent generation series/proposal, and the visible `/retrain` refusal. The
   bodyless retrain call appended one expected `insufficient_data` receipt at
   `2026-08-10T17:01:35.098009Z`; it created no proposal or activation.
2. In ordinary chat, without `/remember`, supplied a durable Moonrise summary
   preference and one project calibration fact. The agent autonomously created
   both. A second ordinary turn corrected BLUE to COPPER and included a clearly
   fake secret-shaped sentinel. The agent edited the same project memory rather
   than duplicating it; the sentinel is absent from every memory head/revision.
   The remote Palace's append-only prompt evidence necessarily retains what the
   scout typed. The local journal that also contained it was later removed with
   the disposable home.
3. A fresh `build-test` thread injected the corrected project memory with raw
   Project 1.000 and answered COPPER. A sibling `m2xs-other-test` thread selected
   no memories and answered that it had no matching project fact. CURRENT Graph
   was empty in the sibling and showed only the project memory after switching
   back; CURRENT Injection followed the same selection while GLOBAL Vitals did
   not move. The visible Project control nevertheless named `m2xs-build-test`
   during the early source-thread captures and `build-test` after reload, so
   item 29 does not pass even though item 22's typed isolation does.
4. Selected `openrouter:openai/gpt-4.1` and sent `/remember` with the exact
   `tests/test_agent.py::LIVE_SPLIT_SOURCE`. One tombstoned source and three
   exact qualifier-complete children were committed atomically. All children
   share the source revision parent, and six directed sibling edges cover every
   ordered pair. No source clause was truncated or blended.
5. Stopped the exact Uvicorn process and restarted the same factory, port, and
   home. Threads and project bindings rehydrated; a follow-up in the restored
   build thread answered `M2XS-COPPER` from its prior history. `nocturne doctor`
   reported a healthy remote Palace, schema 0011, and 839.5 KiB of journal.
   With the exact journal directory changed to mode 0500, host-visible
   `nocturne up --no-open` exited 2 before serving and printed the permissions
   remedy. Mode 0700 was restored immediately.
6. Selected the public-catalog bounded route
   `openrouter:rekaai/reka-edge` (16,384 tokens; $0.10/M input and output), set
   thread-local Max tokens to 8 through Model Device, and used synthetic
   nonsemantic padding. One provider request completed at 11,644 input tokens.
   The next request failed opaquely; no retry or third provider request was
   made.

## Cleanup and residue

Only five exact active verification memories were CAS-tombstoned, at their
fresh revisions, with editor `verification:m2xs` and reason
`M2XS verification cleanup`. The split source was already tombstoned from
birth. A final typed active listing returned zero fixture matches. Two authentic
`local` memories that merely had verification-machine history were explicitly
preserved; no machine-wide cleanup was used.

The retrain `insufficient_data` receipt, verification injections, model/spend
receipts, parameter history, and tombstone revisions are append-only evidence
and remain. There were zero activation attempts. The isolated local daemon was
stopped, browser warnings/errors were empty, and the disposable home was
removed only after the trace and retained evidence were recorded.

## Reproduction notes

The exact app launch shape was:

```sh
env NOCTURNE_HOME=<private-temp-home> \
  PRINCIPAL_ID=m2x-sop-verification \
  MACHINE_ID=m2x-sop-verification \
  AGENT_ID=harness-agent \
  PYTHONPATH=src uv run --locked \
  uvicorn harness.daemon:create_dev_app --factory \
  --host 127.0.0.1 --port 8796
```

Do not replace this with `nocturne up` for a live data pass: the public startup
currently supplies principal `local`. `nocturne up` was used only for the
deliberate pre-service, read-only-journal refusal after port 8765 was confirmed
free on the host.

Secret scan for retained artifacts:

```sh
pattern='sk-or-''v1-|Bear''er [A-Za-z0-9._~-]{16,}|OPENROUTER''_API_KEY\s*=|SPINE''_TOKEN\s*='
rg -n "$pattern" verification/m2xs
```

It must return no matches. The full owner checklist and Garden report 089 are
the verdict authorities; this directory is the supporting evidence packet.
