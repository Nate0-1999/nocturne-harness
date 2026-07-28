# H5 verification — first-prompt memory gate

H5 implements the first-chat prepare → review gate → commit → typed
wrong-memory resolution → model sequence from SPEC C.6, ADR-005, and A-023.
This is builder evidence, not the independent M1 judge verdict reserved by
SPEC B.6.

The fixture keeps the production SPA, `/ws` daemon route, `RunLoop`,
`MemoryGateTurnRunner`, typed C.4 client, and the deployed Spine configured by
the ignored `Harness/.env`. Only the downstream model is replaced with a
deterministic pydantic-ai `FunctionModel`, so browser evidence never spends a
hosted chat-model call. Trace output contains no credential or raw arbitrary
prompt: prompts are SHA-256 digests, while the exact final block contains only
the fixture's deliberately non-sensitive seed text.

## Start the fixture

From the Harness repository root:

```sh
npm run build --prefix web
PYTHONPATH=src uv run uvicorn scenario_app:create_scenario_app --factory \
  --app-dir verification/h5 --host 127.0.0.1 --port 8765
```

The command intentionally fails closed when `SPINE_TOKEN` is absent. It reads
`SPINE_URL` and `SPINE_TOKEN` from the ignored `.env`, then overrides only the
principal/machine/agent identities with fixture-specific values.

In another terminal, seed a fresh isolated principal:

```sh
curl -fsS -X POST http://127.0.0.1:8765/__scenario__/seed
curl -fsS http://127.0.0.1:8765/__scenario__/expectation
```

Seeding uses only C.4 `POST /v1/memories` and `PATCH /v1/memories/{id}`.
Four cards are patched to `pin=true`, guaranteeing they are injected. The
fixture advertises a one-token model context, so the only regular card has no
regular-token budget and deterministically appears as the sole near-miss.

Use these exact prompts in one fresh browser thread:

```text
Use the H5 verification memories to explain the handoff.
Confirm that the second prompt skips the memory gate.
```

For the first prompt, leave `H5 proof — keep`; remove the three named cards
with their matching `not_relevant`, `wrong`, and `never` reasons; add back
`H5 proof — add back`; then Continue. The model must remain stopped while a
second **Wrong memory resolution** gate opens for `H5 proof — wrong`. Leave
**Edit body** selected, replace the body with this exact text, and choose
**Save correction**:

```text
The first-prompt memory gate waits for a human decision before the model starts.
```

Before saving the correction, prove the second hard pause from another
terminal:

```sh
curl -fsS -X POST http://127.0.0.1:8765/__scenario__/assert-wrong-paused
```

Only after that CAS-guarded PATCH succeeds may the gate dismiss and the
deterministic response render. Then send the second prompt. The second prompt
must run directly without a gate.

Assert the resulting service/model ordering and exact decisions:

```sh
uv run python verification/h5/assert_trace.py
```

The assertion requires one prepare, explicit hard-pause observations at both
gate stages, one review commit, the returned current `wrong_removed` unit, one
exact `gate/wrong:edit` PATCH and result before the first model call, the exact
committed `final_block` as the suffix of that model call's system-adjacent
instructions, a second model call with only its static capability instructions
and no prepare/gate block, and exact kept/removed/added-back membership.

## Desktop and phone evidence

Drive the built UI through the in-app browser at 1440×900 and 390×844. For
each viewport, cleanup and seed again so `never` feedback cannot accumulate
across evidence runs:

```sh
curl -fsS -X POST http://127.0.0.1:8765/__scenario__/cleanup
curl -fsS -X POST http://127.0.0.1:8765/__scenario__/seed
```

Capture each acceptance-relevant rendered state under this directory:

For a post-A-022 rerun, put new files in a dated subdirectory; do not overwrite
the historical evidence listed below.

- `01-gate-open-desktop.jpg` / `07-gate-open-mobile.jpg` — full bodies,
  overall score, and all six raw feature scores are readable.
- `02-default-remove-desktop.jpg` / `08-default-remove-mobile.jpg` — a plain
  one-tap/click × marks the not-relevant card without a second dialog.
- `03-modifier-menu-desktop.jpg` / `09-modifier-menu-mobile.jpg` — the
  long-press or Alt-× menu visibly offers Wrong and Never.
- `04-decisions-desktop.jpg` / `10-decisions-mobile.jpg` — the near-miss is
  visibly added before Continue; the exact three removal reasons plus add-back
  are proved by the corresponding canonical trace rather than a single frame.
- Capture an additional append-only frame at each viewport showing the
  `wrong_resolution` editor before submission.
- `05-committed-run-desktop.jpg` / `11-committed-run-mobile.jpg` — both gate
  stages have completed and the deterministic model answer is rendered.
- `06-second-prompt-desktop.jpg` / `12-second-prompt-mobile.jpg` — the second
  prompt completes without another gate.

While the initial gate is visibly open, wait at least five seconds and record
the explicit no-model/no-commit pause check from a second terminal:

```sh
curl -fsS -X POST http://127.0.0.1:8765/__scenario__/assert-paused
```

At each viewport also assert `scrollWidth == clientWidth`, the gate can scroll
to every full body without hiding Continue, controls meet the 44×44 CSS-pixel
target, background chat is inert while the modal is open, Escape does not
bypass the hard pause, Enter commits only a complete valid decision, and the
browser console has no warning or error.

To preserve separate canonical traces, copy after each completed run and
assert both copies:

```sh
cp verification/h5/trace.jsonl verification/h5/trace-desktop.jsonl
uv run python verification/h5/assert_trace.py verification/h5/trace-desktop.jsonl

# cleanup, seed, repeat at 390×844, then:
cp verification/h5/trace.jsonl verification/h5/trace-mobile.jsonl
uv run python verification/h5/assert_trace.py verification/h5/trace-mobile.jsonl
```

## Executed result — 2026-07-21

> Historical evidence: this run predates A-023 and therefore proves the former
> one-stage flow only. Keep its screenshots and traces as append-only evidence;
> they do not satisfy the current wrong-resolution PATCH assertion.

The built SPA was driven through the in-app Chromium browser against the
deployed Spine at both required viewports. Every image is verified JPEG/JFIF
with an extension matching its bytes.

| State | 1440×900 | 390×844 | Result |
|---|---|---|---|
| Gate open before model | [01](01-gate-open-desktop.jpg) | [07](07-gate-open-mobile.jpg) | PASS |
| Plain × means not relevant | [02](02-default-remove-desktop.jpg) | [08](08-default-remove-mobile.jpg) | PASS |
| Wrong/Never modifier menu | [03](03-modifier-menu-desktop.jpg) | [09](09-modifier-menu-mobile.jpg) | PASS |
| Near-miss add-back and final counts | [04](04-decisions-desktop.jpg) | [10](10-decisions-mobile.jpg) | PASS |
| Exact three removals plus add-back | [desktop trace](trace-desktop.jsonl) | [phone trace](trace-mobile.jsonl) | PASS |
| Commit dismisses before response | [05](05-committed-run-desktop.jpg) | [11](11-committed-run-mobile.jpg) | PASS |
| Second prompt skips the gate | [06](06-second-prompt-desktop.jpg) | [12](12-second-prompt-mobile.jpg) | PASS |

Both [desktop](trace-desktop.jsonl) and [phone](trace-mobile.jsonl) canonical
traces passed the eight-record assertion. The pause probe returned one prepare
result with zero commit and model calls after more than five seconds. Document
widths were 1440/1440 and 390/390; every gate control was at least 44×44 CSS
pixels; the browser console had no warning or error.

The fail-open checks also passed: [prepare failure](13-prepare-fail-open.jpg)
opened no gate, while [commit failure](16-commit-fail-open.jpg) dismissed the
gate; both displayed the exact warning and completed a memoryless model call.
Their committed [prepare trace](trace-prepare-fail.jsonl) and
[commit trace](trace-commit-fail.jsonl) prove the one-shot failure ordering,
absence of a commit result, and absence of seeded memory text or an injection
block in the downstream model instructions.

A five-minute unscripted pass covered live resize, double-click, modifier
recovery, inert backdrop scrolling, reload reconstruction, and a 320-pixel
narrow check ([resize](14-exploration-resize.jpg),
[reload](15-exploration-reconnect.jpg)). See [SOP.md](SOP.md) for first-person
observations and the deliberately retained friction.

Repository gates completed as follows:

```text
Harness non-contract suite        243 passed, 2 deselected
Gate/daemon asyncio-debug suite    51 passed (warnings fatal)
Live migrated Spine contract        2 passed
Sibling Spine full suite           160 passed
Web ESLint                          passed
TypeScript + Vite production build passed (25 modules)
Ruff lint / format                  passed (30 files formatted)
uv lock / trace / diff checks       passed
```

The sibling suite used `TESTCONTAINERS_RYUK_DISABLED=true` because this local
Colima socket cannot be bind-mounted into the reaper; its temporary database
still exited normally. The live contract runner removed its containers,
network, volume, and locally built image. No H5 fixture process or remote seed
remained after exact-ID cleanup.

## Adversarial memory-unavailable controls

The controls fail one operation before it reaches Spine, once, without
altering credentials or stopping the deployed service:

```sh
curl -fsS -X POST http://127.0.0.1:8765/__scenario__/fail-next/prepare
curl -fsS -X POST http://127.0.0.1:8765/__scenario__/fail-next/commit
```

Run each against a fresh thread. The UI must surface the clear memory warning
and still render the deterministic chat response. A prepare failure opens no
gate. A commit failure dismisses the open gate and continues without injected
instructions. Assert the committed traces with:

```sh
uv run python verification/h5/assert_trace.py \
  --failure-phase prepare verification/h5/trace-prepare-fail.jsonl
uv run python verification/h5/assert_trace.py \
  --failure-phase commit verification/h5/trace-commit-fail.jsonl
```

Reset before a canonical happy trace:

```sh
curl -fsS -X POST http://127.0.0.1:8765/__scenario__/reset
```

## Exact cleanup

Always finish with:

```sh
curl -fsS -X POST http://127.0.0.1:8765/__scenario__/cleanup
```

Cleanup never issues DELETE and never lists or bulk-mutates a principal. It
CAS-patches only the exact IDs retained from this process's seed responses to
`status=tombstoned`; if gate feedback advanced a revision, it retries only
that same ID using the revision returned by the typed conflict.
