# M2UX2 independent browser SOP

Date: 2026-08-11

Harness source: current checkout plus the uncommitted M2UX2 diff under review

Real owner composition: `harness.daemon:create_dev_app`, isolated verification
identity, private disposable home, port 8803

Deterministic archive fixture: `M2UX2 REGRESSION`, private disposable home,
port 8802

## Motivation

The scripted crawl proves routing, but a source assertion cannot prove that a
human can see and operate the return path through the Rack's iframe boundary.
I therefore walked the current production SPA in the in-app browser against a
separate real owner daemon. I did not restart or interact with the active owner
daemon on port 8765.

## Walk

1. I first opened port 8765 and opened Queue read-only. It was healthy but,
   because that daemon predates this build, it still served the previous asset
   snapshot and showed **Close queue**. I used no mutating control and did not
   reload or stop it.
2. I launched the current real owner composition on port 8803 with principal,
   machine, and agent `m2ux2-sop-verification`. Opening it created only the
   ordinary empty local journal in its disposable home.
3. At desktop width I opened **Palace queue**, **Graph**, **Injection**, and
   **Model** in turn. Every surface exposed the same visible **← Back to stage**
   control, and each click restored the stage before I opened the next view.
   The retained deterministic desktop appearance is
   `01-graph-back-to-stage-1280x900.png`.
4. I changed to 390×844 after returning from Model, opened **Threads**, used its
   visible **Back**, then opened **Memory** and used its visible **Back**. This
   desktop-to-phone round trip was the unstructured exploration; no control
   disappeared and no hidden scrim was needed.
5. The real thread catalog exposed **Archive New thread** on the exact empty
   row. I did not click it: doing so would ask the production Palace to prepare
   extraction. The isolated rendered fixture independently clicked the row
   action, observed `POST /v1/threads/{thread_id}/archive`, entered the ordinary
   Thread End review with exactly five pending thread candidates, and returned
   to the stage. `02-thread-list-archive-review-390x844.png`,
   `03-stage-restored-390x844.png`, and `crawl.json` preserve that proof.
6. I read the owner-browser warning/error log after the walk; it was empty.
   Opening Injection issued the product's automatic scorer-simulation POST.
   The Spine implementation runs that request inside a `REPEATABLE READ READ
   ONLY` transaction; I did not press Force Retrain or any other write control.
7. I reset the temporary viewport, finalized both browser tabs, stopped only
   the exact port-8803 daemon, proved ports 8802 and 8803 had no listeners, and
   removed only the two validated disposable homes.

## Result

PASS. All seven reachable dismissible surfaces have one obvious return action;
the catalog presents archive at the chosen thread; and the rendered fixture
proves that action reuses ordinary consent-bearing extraction rather than
deleting the thread or inventing a second lifecycle.

No prompt, provider request, memory creation, archive request against the real
Palace, scorer activation, owner-identity write, deployment, or cloud mutation
was performed. The automatic simulation was read-only. No disposable home or
verification listener remains.
