# Decision journal

## 000 — Relay law [P4]

> Read docs/SPEC.md 1 -> 2 -> B -> C before touching dirt. Every entry in this journal cites a Problem Tree node. Local defects follow the Blight Protocol (SPEC 2.1). Features that cannot name their problem do not get built.

## 001 — Bootstrap tooling [P4]

**Decision.** Package the Python 3.12 daemon with Hatchling; expose the
required `harness dev` command as a project script; use Ruff and pytest for
the bootstrap gates; use a minimal Vite + React + TypeScript web scaffold
with npm's committed lockfile and ESLint; validate C.7 envelopes strictly
with Pydantic v2; keep C.4 response shapes that the spec does not define (the
PATCH "unit", PATCH conflict, and paged list) as opaque JSON objects; and
make `harness dev` run the locked web install/build before binding the
development daemon to loopback port 8765.

**Motivation.** These choices keep package metadata, developer commands,
dependency graphs, and CI checks deterministic; provide the literal C.1
React/TS/Vite boundary without implementing H4 behavior; make the literal
C.7 seam executable immediately; avoid manufacturing missing C.4 contract
fields; make the documented developer command sufficient on a fresh clone;
and provide a deterministic local port without encoding localhost into
browser code or messages.

**Rejected alternatives.** A bespoke task runner, an unpinned frontend
dependency graph, and a larger UI framework add bootstrap machinery without
P0 capability. Server rendering would erase the explicit C.1 web boundary.
Requiring a separate undocumented web build would make the P0 developer
command incomplete, while committing generated `dist/` assets would create
source/build drift.
Permissive envelope parsing weakens the relay seam. Inventing pagination or
memory-unit fields would turn an implementation guess into cross-repository
law. Binding publicly by default needlessly enlarges the P0 surface.

## 002 — Tracked M1 scope fence [P4]

**Decision.** Keep a repository-owned pre-commit hook that scans staged files
for the forbidden M1 feature families named by Garden Plan §7, and run the
same check over all tracked files in CI. Exclude the hook itself, frozen law,
decision/report Markdown, lockfiles, and verification artifacts from the
pattern scan; those files necessarily name forbidden concepts while defining
or evidencing the boundary.

**Motivation.** A local-only hook configuration disappears on clone. Tracking
the small POSIX script and repeating it in CI makes the scope boundary visible
and reproducible without adding a hook framework.

**Rejected alternatives.** A dependency-heavy pre-commit framework adds no
useful P0 capability. Scanning `docs/SPEC.md` or the hook's own pattern list
would make every run fail on the words that define the prohibition.

## 003 — Adopt the enacted v1.5 C.4 completion [P1.1]

**Decision.** This is an adoption record, not a local contract choice. The
human-enacted SPEC v1.5 resolution in Garden FLAGS F001–F005 and SPEC D.2
entry 028 supersedes Entry 001's temporary opaque C.4 response models. Mirror
the enacted shared `MemoryUnit`; context-specific `MemoryCard` feature/rank
values; `wrong_removed`; create/PATCH `machine_id`; create `force`; label and
revision conflicts; exact create/PATCH/list responses; and `limit`/`offset`
query fields in the typed Harness seam.

**Motivation.** The two repositories couple through C.4. Recording the
supersession keeps the append-only journal historically honest while making
the current human-approved contract unambiguous to H2 and later readers.

**Rejected alternatives.** Rewriting Entry 001 would erase why P0 originally
refused to invent contract law. Leaving its opaque-model note as the journal's
last word would misdirect H2. Declaring a competing local completion would be
both redundant and beyond P0 authority because v1.5 already supplies the law.

## 004 — Closed-set WebSocket routing without payload invention [P3]

**Decision.** Adopt Garden A-013 for inbound C.7 framing. Parse one strict JSON
text frame at a time, reject binary, invalid, non-object, or schema-invalid
frames with the enacted 1008 close, and dispatch each validated envelope once
through a complete `MessageType` route table. Let the app factory copy optional
handler overrides; each async handler receives the validated envelope and an
envelope-only sender so it may emit zero or multiple C.7 messages. Preserve the
P0 `error: not implemented` response as the default route for every type until
a later packet supplies that type's behavior. Register a final WebSocket-only
catch-all before the root static mount so unknown socket paths close cleanly
instead of entering Starlette's HTTP-only static application.

**Motivation.** The copied table avoids shared mutable connection state while
making routing directly testable. A sender callback is the smallest transport
shape that can carry C.7's streamed `run.delta` messages without coupling a
handler to FastAPI or prematurely defining payloads. Exact outer validation
keeps malformed input out of every later business handler.

**Rejected alternatives.** Per-type payload models, browser-versus-daemon
direction rules, acknowledgements, and correlation semantics are absent from
C.7 and belong to later behavior packets. A global mutable registry would leak
handlers across app instances and tests. Passing the raw WebSocket into
handlers would couple business code to transport, while a one-response return
value would make the named stream type dishonest. Swallowing handler failures
into a new error schema would invent behavior the contract does not define.

## 005 — Literal Spine boundary with a hermetic live contract [P1.1]

**Decision.** Adopt the current C.4 surface, including Garden A-014's positive
prepare-context bound, A-012's search bound, the enacted list bounds, and the
v1.6 `origin_path` fields. Give each `SpineClient` one owned asynchronous HTTP
client; ownership includes any caller-supplied test transport and ends through
`aclose` or the async context manager. Send relative C.4 routes beneath a
validated, credential-free absolute HTTP(S) base URL with bearer auth, no
redirects, no retries, and JSON bodies that omit optional nulls. Validate each
response against its exact status, media type, strict standard-JSON body model,
and RFC7807 semantics without scalar coercion. Surface RFC7807 responses,
create conflicts, and PATCH conflicts as distinct typed exceptions that retain
the raw response without copying its body or credentials into exception text.

Run S1–S2 contract assertions in an unconditional CI job against the production
Spine Dockerfile at commit `9c51c992b6103ee7492961bcb27fb608c4760446`, a
disposable pgvector PostgreSQL service, and both Spine migrations. At test
composition only, mount a Harness-owned app factory that supplies a closed set
of deterministic 1536-dimensional embeddings through Spine's existing
provider-injection seam. Tear down the database, network, containers, volume,
and locally built image after every run.

**Motivation.** Exact status-correlated decoding keeps API drift visible to the
daemon instead of letting structurally similar success and conflict bodies pass
under the wrong semantics. Exercising the public client against a migrated,
real HTTP and pgvector stack proves the cross-repository boundary without cloud
credentials, external model calls, or changes to Spine production code.

**Rejected alternatives.** Mock-only tests cannot detect routing, migration,
serialization, or container-startup drift. Following a mutable Spine branch
would make Harness CI change without a Harness commit. A generated client adds
another build artifact without reducing this seven-route surface. Retrying
mutations risks duplicate decisions, while following redirects could send the
bearer token outside the configured service. Calling OpenAI or the deployed
cloud service would make routine verification depend on credentials, quota,
cost, and mutable external state; adding a fake provider to Spine production
would widen that repository solely for this packet.

## 006 — Owned H3 capability seam at the first real use [P1.2]

**Decision.** Implement ADR-013 with frozen, Harness-owned Pydantic models for
all five named protocol axes: instructions, tools, lifecycle hooks, history
transforms, and event-stream taps. H3's first feature populates only instructions
and tools; the other typed tuples remain empty until first use. Keep the memory
feature and all three handlers free of pydantic-ai imports. Translate that
definition in the sole `pydantic_ai_adapter.py` module through explicit
contextual wrappers, and ship
`MemoryCapability` as a standard capability with stable id `memory` and
`defer_loading=False`. Pin the direct pydantic-ai dependency to the locally
verified 2.12.0 API because CI installs from `pyproject.toml`, not `uv.lock`.

**Motivation.** This is the smallest executable form of the two-module law:
Harness owns the feature contract and pydantic-ai is replaceable adapter
machinery. Explicit wrappers preserve useful model schemas while invoking the
handler carried by the owned definition. The exact pin keeps the Capability,
RunContext, Tool, and Agent APIs from changing underneath an otherwise
unchanged commit.

**Rejected alternatives.** Importing capability machinery directly into the
feature or tools would pierce the grep-friendly seam. Dynamic `**kwargs`
wrappers erase useful tool schemas. Implementing unused lifecycle, history,
event, deferred-loading, CodeMode, or upstream-battery behavior would be
speculative milestone work; the owned axes exist without pretending H3 uses
them. Depending wholesale on pydantic-ai-harness or leaving the direct
dependency floating would surrender the boundary ADR-013 exists to own.

## 007 — Trusted memory context and conservative mutation semantics [P1.4]

**Decision.** Adopt Garden A-015: expose `force=False` on `save_memory`, forward
the model's value once, and never infer or retry it. Supply principal, machine,
agent, thread, project, and path only through frozen run dependencies; agent
writes use `editor=agent:<agent_id>`. A project-scoped save without a current
project stops before Spine, while an unscoped save is global. Search carries
the current project and renders response order as compact deterministic JSON
lines. Resolve edit targets among all ACTIVE rows for the trusted principal by
UUID first, then exact case-sensitive label, paging in 200-row C.4 pages with no
project filter. PATCH only the body and retry exactly once only when Spine
returns a revision conflict, using that response's current revision.

**Motivation.** Model arguments describe memory content and intent, never
authority. Principal-wide exact resolution respects active-label uniqueness
without inventing a GET-by-id route or hiding global/cross-project matches.
Compact cards preserve the C.4 information needed to choose an edit, and the
single compare-and-swap retry implements C.6 without turning a conflict into an
unbounded mutation loop. Similar, duplicate, label, protocol, and transport
outcomes remain visible instead of masquerading as success.

**Rejected alternatives.** Model-supplied identity or scope is an authority
leak. Automatic force would bypass the human/model decision C.6 explicitly
requests. Substring or first-result edit resolution can mutate the wrong unit;
adding a Spine route would disturb a completed contract packet. Retrying label
conflicts or a second revision conflict would exceed the one-retry law. A
guessed secret regex was not added: C.6 supplies a verbatim agent instruction,
not a deterministic storage policy, and silently inventing one would create
false security semantics.

## 008 — Bounded chat and tools-free `/remember` service [P1.2, P1.4]

**Decision.** Correct the development/testing default to
`openrouter:minimax/minimax-m3`; add the C.5 request/token limits, label bound,
and existing Spine URL to Harness settings. Resolve OpenRouter, Anthropic, and
OpenAI models with settings-owned secrets passed to explicit providers rather
than copying secrets into process environment. Reject other direct providers;
OpenRouter is C.5's deliberate any-model escape hatch. Ordinary chat mounts
only `MemoryCapability`, preserves opaque pydantic-ai history for the next turn,
and applies the 40-request/500,000-token walls. `/remember` is a service-level
dispatch seam for later daemon wiring: a separate tools-free agent uses the
same selected model under a one-request wall, then the command validates one
nonblank, single-line label of at most 64 Unicode code points and performs one
global `kind=fact`, `editor=user`, `force=false` create with trusted provenance.
Only a 201 creation receives a generated chat confirmation.

**Motivation.** Settings loaded from `.env` must reach provider constructors
without relying on unrelated global environment state. A separate label agent
prevents a label completion from invoking memory tools, while the one-request
wall makes "one short completion" architectural rather than aspirational.
Returning framework-neutral chat/command results gives H4/H7 a callable seam
without inventing their still-owned WebSocket payload and loop behavior.

**Rejected alternatives.** The stale Sonnet development default contradicted
C.5. Reusing the chat agent for labels exposes three unrelated tools; a second
model call for confirmation spends attention and tokens without adding truth.
Truncating, regenerating, auto-forcing, or silently retrying a bad label or
non-created response could save something other than the explicit command.
Wiring current placeholder daemon routes would pre-empt H7/H4, while adding
prepare/gate/commit behavior would trespass on H5.

## 009 — Authoritative process-local run loop [P3]

**Decision.** Adopt Garden A-016 as the executable C.7 v1.12 completion. Keep
one process-scoped `RunLoop` with independent per-thread transcript, opaque
provider history, active run, memory-gate snapshot, and FIFO. Serialize state
transitions under one lock, but never perform model, tool, or socket work while
holding it. Give every connection one ordered delivery worker with a 256-event
buffer and give its WebSocket writer a second 256-envelope outbox; a subscriber
that cannot stay inside that wall is detached from live delivery and recovers
from the authoritative snapshot rather than consuming unbounded daemon memory.
Confirm snapshot delivery into the connection outbox before later direct-route
responses, shield terminalization from finish/cancel races, and never issue a
second task cancellation while tool cleanup is already in progress. Keep a
small injectable envelope factory for fresh ULIDs, time, and daemon identity.

**Motivation.** Connection-owned state cannot satisfy reconnect hydration or
preserve a run through a dropped socket. A process-local scheduler is the
smallest M1 lifetime that can make cancellation, queue boundaries, and
snapshot-first ordering exact. Separate UI transcript and provider history
let the browser hydrate stable JSON without coupling it to pydantic-ai message
classes. The two bounded queues preserve event order and least-attention
operation for healthy clients while making a stalled client a recoverable
snapshot problem instead of a daemon-wide memory leak.

**Rejected alternatives.** Replaying deltas on reconnect contradicts C.7.
Awaiting the model in the socket reader makes cancel and queue input
unreachable. One delivery task per event and unbounded outboxes fail under a
non-reading client. Holding the state lock across external sends lets one dead
socket stop every run. Cross-process persistence, queue editing, steering,
checkpointing, and retry machinery are later-milestone behavior, not H7.

## 010 — Pydantic run adapter and trusted dev composition [P3, P1.4]

**Decision.** Drive ordinary turns through `Agent.run` with an event-stream
handler, caller-owned cumulative usage, and `capture_run_messages`; translate
text and thinking explicitly and carry every other JSON-safe pydantic event
under C.7's event delta. On cancellation, wait for tool teardown and repair
each unanswered regular tool call using public `ModelRequest` and
`ToolReturnPart(outcome="interrupted")` values before returning the preserved
history. Treat a cleanup exception as cancelled when the asyncio task still
has a cancellation request. Let `/remember` keep its direct-service visible
failure behavior for callers, but let the run adapter request propagation of
label-provider and budget failures so run.done and usage stay truthful.

Make `harness dev` use a separate `create_dev_app` composition: one
lifespan-owned Spine client, one `HarnessAgent`, one `PydanticAITurnRunner`, and
settings-owned single-user `principal_id`, `machine_id`, and `agent_id`
defaults. Parse the C.7 thread ID as a UUID only at the trusted memory-tool
context boundary. Keep `create_app` dependency-injectable with an honest error
runner so transport/loop tests never require credentials or hosted calls.

**Motivation.** The public event and message-capture seams preserve partial
work across model, tool, budget, and provider exits while keeping the owned run
protocol independent of pydantic-ai. Explicit trusted composition makes the
H3 adapter reachable from the actual developer command without accepting
identity from model payloads or manufacturing an authorization system. The
separate test factory keeps all verification hermetic.

**Rejected alternatives.** Serializing pydantic-ai history into snapshots
would turn a pinned framework detail into browser law. Its private dangling-
tool repair helper is not a stable seam. Swallowing label-agent failures makes
budget exhaustion look like a successful turn. Model-supplied identity is an
authority leak; global credential environment mutation and hosted test calls
make behavior non-local; adding another provider retry layer would implement
ADR-014's later retry scope early.

## 011 — Snapshot-first direct chat shell [P2, P3]

**Decision.** Adopt Garden A-017 and A-018 with one Zustand store, one
same-origin WebSocket owner, and no client router. Persist only the browser's
local UUID thread catalog; replace transcript, active run, gate, and usage from
each matching daemon snapshot. Keep successfully sent but unacknowledged
prompts in a volatile overlay so an overlapping attach/request snapshot cannot
erase their only text copy. Recover bounded-delivery close 1013 by reconnecting
and requesting the selected snapshot, never by replay or polling.

Use a restrained near-black, warm-white, steel, and orange two-pane shell on
wide screens and a single-pane thread view at 390×844. Preserve quiet
full-width message rows, explicit queue/stop/usage states, reader-controlled
scroll position, 44px controls, and coral only for errors. Do not render the
future memory gate, Memory panel, Cube, decorative cosmos, or placeholder
controls. NATES_VISION §8 names self-hosted Inter, JetBrains Mono, and extended
display faces, but this checkout contains no licensed font assets. H4 therefore
uses explicit system/local fallbacks rather than adding a network font request
or fabricating font files; adopting committed licensed assets is deferred to a
packet that actually supplies them.

**Motivation.** Snapshot authority and a separate pre-ack overlay make reload,
queue, cancellation, and backpressure behavior coherent without inventing a
server thread-list API. The visual choices keep attention on the conversation,
remain readable and keyboard-operable on the required phone viewport, and
follow the vision's hierarchy and palette with no external runtime dependency.

**Rejected alternatives.** Server-side thread enumeration/persistence, client
replay buffers, polling, route machinery, a component framework, and another
state store add behavior H4 does not need. A font CDN makes the local shell
network-dependent, while fake bundled font files would be dishonest evidence.
Prebuilding H5/H6 surfaces or ornamental scaffolding would violate the M1 scope
fence and least-attention invariant.

## 012 — One-shot first-chat memory gate [P1.2.1a–c, P2, P3]

**Decision.** Adopt Garden A-019 as the executable H5 boundary. Wrap the
framework-neutral turn runner with one process-lifetime gate attempt per thread:
the first ordinary chat prepares against Spine, resolves one `RunLoop`-owned
future from a strictly correlated browser decision, commits with the
server-held injection ID, dismisses, and passes the exact final block as
system-adjacent pydantic-ai instructions. `/remember` neither opens nor consumes
the attempt. Source the context window from positive
`MODEL_CONTEXT_TOKENS=1000000`, aligned with the default M3 model.

Carry the full C.4 scored-card shape over exact `gate.open`/`gate.commit`
extensions and render full bodies, total score, UUID, and all six raw M1 feature
scores in a native modal dialog. A plain × means `not_relevant`; Alt-× or touch
hold exposes Wrong/Never; near misses are explicit add-backs. Keep Stop and
Continue inside the modal, preserve choices only for its mounted lifetime, and
reject Escape, backdrop, queued prompt, malformed cards, stale correlation,
membership drift, duplicate IDs, and double submission. Only a typed Spine
prepare/commit failure fails memory open with a visible warning and a memoryless
chat call; validation and programming faults remain run errors.

Verify the entire path with a fixture that keeps the production SPA, WebSocket,
daemon, run loop, typed client, and deployed Spine, replacing only the
downstream chat model with a streaming deterministic `FunctionModel`. Seed and
clean only retained exact IDs, pin four cards, force one regular near miss with
a one-token fixture context, hash arbitrary prompts in traces, and preserve
separate desktop/mobile traces and rendered evidence. B.6 rule 8 adds a
first-person SOP, fail-open screenshots, and unscripted friction alongside the
deterministic assertions.

**Motivation.** A server-owned future makes the hard pause a lifecycle fact,
not UI timing, while exact correlation and membership validation keep browser
state from becoming authority. Dynamic instructions preserve the user prompt
as user data and place committed memory where the model expects trusted
context. Native dialog/inert behavior, sticky 44px controls, and full raw-score
cards make the one consequential review interrupt legible on desktop and
phone. Deployed-Spine evidence covers the semantic path without spending or
masking a hosted chat call.

**Rejected alternatives.** A timeout or automatic continue violates ADR-005.
Letting `/remember` consume the gate surprises the next ordinary chat. Trusting
the browser's injection ID, retrying stale commits, or caching an offline block
weakens the authority boundary. Rendering M2 weighted contributions would lie
about C.4's raw features. Folding command parsing into the agent adapter couples
service routing to pydantic-ai, so the parser lives in a small framework-free
module. H6 editing, per-prompt rescoring, retry UX, durable gate persistence,
and explanatory training copy remain later work rather than H5 scope creep.

## 013 — Turn-bound removals and conservative save scope [P1.2.1a, P1.4]

**Decision.** Carry committed gate removals into the model adapter as an
immutable, trusted, per-run set of memory IDs. The adapter places that set on
the fresh `MemoryToolContext`; search overfetches only enough to replace
excluded rows within C.4's 50-result wall, removes excluded IDs before
rendering, and then reapplies the requested limit. The exclusion expires with
the run rather than mutating Spine or becoming a thread blacklist. A-023 remains
the authority for resolving `wrong_removed` units under the hard pause before
this model run begins.

When a project-scoped save has no current project, mark that trusted run
context and surface the missing-context result. Reject every later global save
in the same run, and instruct the agent that global fallback requires explicit
user confirmation in a later user turn. A fresh run context is the boundary
after that confirmation; no model argument can clear the guard.

**Motivation.** Gate corrections must bind every memory path visible to the
same answer, not only the precomputed final block. Filtering at the owned tool
boundary closes search re-entry without changing scorer state or the completed
Spine contract. The save guard converts the v2.16 no-silent-broadening rule
from prompt etiquette into a deterministic same-run wall while still allowing
the user to make a different explicit choice later.

**Rejected alternatives.** Prompt-only exclusion can be bypassed by a tool
call, while deleting or tombstoning every rejected unit would change C.4
lifecycle semantics. A persistent thread blacklist would make a one-turn gate
choice outlive its contract. Automatically retrying project saves globally
violates P1.4 authority boundaries; permanently banning later global saves
would ignore an explicit user correction. A second confirmation UI is not
needed for this tool boundary because the later user turn supplies the
confirmation boundary, while A-023 separately owns the typed correction stage.

## 014 — Trusted live-memory panel and frozen thread context [P1.2.1d, P1.3]

**Decision.** Adopt Garden A-024 as the H6 browser boundary. Keep the panel on
the existing bidirectional WebSocket envelope and derive principal, machine,
editor, PATCH reason, and injection ID in the daemon. Page the complete C.4
ACTIVE list, filter it to the configured principal before it crosses the
browser boundary, and correlate every state, conflict, or safe error to the
request envelope.

Bind each successfully committed injection's exact canonical fragments to its
server-held member IDs in a daemon-lifetime per-thread registry. A panel remove
submits `mid_thread_removed` with that registry's injection ID, mutates the
registry only after `{ok:true}`, and persists the removed ID in the thread's
memory-tool exclusions. Serialize that feedback boundary with the complete
model run so a successful removal cannot race a later provider request that
still holds stale instructions or tool context. Before each later turn, remove
historical dynamic memory blocks and supply exactly the registry's current
block. Body edits and manual pins use the displayed revision once, surface the
typed current unit on a validated CAS conflict, and leave the already-committed
thread block frozen.

Render a persistent restrained memory rail on desktop and a focus-contained
drawer at 390×844. Treat daemon state as authoritative: show current-context
versus stored state, permit Remove only for current members, preserve an edit
draft across a conflict, and require the user to retry explicitly. Refresh
after authoritative thread snapshots and completed runs, plus direct user
requests; do not poll.

**Motivation.** Exact fragment retention preserves the committed injection
event rather than reconstructing it from mutable MemoryUnits. The shared
run/feedback boundary makes “next model call” a concurrency guarantee, not a
UI timing assumption. Principal filtering and server-owned provenance keep the
browser useful without making it an authority, while visible CAS replacement
preserves deliberate human control.

**Rejected alternatives.** Browser-supplied identity or injection IDs create
an authority leak. Re-rendering current context after edit or pin violates the
frozen-injection contract. Retrying a 409 silently overwrites concurrent work.
Polling adds traffic and race states that snapshot/run completion already
cover. Callable live instructions and a second persistence layer are not
needed once feedback and provider runs share one narrow serialization
boundary.

## 015 — Composer hit-target correction [P3]

**Decision.** Raise the chat textarea's minimum rendered height from 32px to
44px after the H6 live responsive audit measured the actual interactive
element rather than its larger surrounding form. Keep the existing composer
layout, typography, and auto-growth ceiling unchanged.

**Motivation.** A visually generous wrapper does not make its nested textarea
an adequate phone target. Correcting the deepest local control closes the
observed accessibility defect without redesigning the chat shell.

**Rejected alternatives.** Treating the wrapper as the hit target would make
the evidence untrue. Enlarging every composer dimension or adding a separate
mobile layout would exceed this local P3 remedy.

## 016 — Safe rich text, thread-owned model truth, and keyword-complete remember [P2, P3]

**Decision.** Render assistant content with `react-markdown` plus `remark-gfm`
through a narrow element allowlist covering the H8 headings, emphasis, lists,
tables, and code contract. Keep raw HTML handling disabled so source tags remain
visible inert text, style only through the existing theme tokens, and leave user
messages on React's plain-text path. Carry the daemon-owned resolved model as an
optional nonblank C.7 extension on both `thread.snapshot` and `run.started`;
seed it from the static chat configuration in M1, let the browser refresh its
runtime-only thread state from either authoritative event, and degrade older
daemon frames to an explicit waiting state rather than inventing a model name.

Generate `/remember` metadata with one request-limited, tools-free
`PromptedOutput` completion returning a typed label and keyword list. Normalize
keywords to distinct lowercase terms and reject the draft before persistence
unless two through five nonblank terms survive. Send those terms on the same
user-authored memory create request, and put the SPEC's keyword mandate in the
ordinary memory capability instruction as well.

Ship the local Harness mark as an SVG favicon. It removes the browser's
otherwise automatic missing-favicon request, keeping the product console clean
without adding an asset pipeline or a network dependency.

**Motivation.** A maintained CommonMark/GFM renderer is a smaller security and
correctness surface than a local parser, while the explicit allowlist preserves
the product's restrained typography and keeps provider text out of the DOM
authority boundary. Snapshot/start model state gives the human truthful
per-thread visibility now and one stable display seam for H9 without moving
configuration into the browser or building the M2 selector. One structured
metadata completion closes the live retrieval defect without doubling provider
traffic or allowing a label save to land keyword-less.

**Rejected alternatives.** `dangerouslySetInnerHTML`, `rehype-raw`, and a
handwritten Markdown parser all widen the untrusted-rendering surface. Reading a
Vite environment value would show process configuration rather than the
thread's eventual H9 resolution; implementing the H9 policy resolver or an M2
selector here would cross the packet fence. A second keyword completion wastes a
request, while silently accepting an invalid list recreates the gate-day data
defect H8 exists to close. Suppressing favicon errors in the fixture would hide
a real baseline request instead of closing it in the product.

## 017 — Auditable per-thread model policy and broker-sticky routing [P4, P4.2]

**Decision.** Adopt Garden A-020, A-021, A-025, and A-026 as the executable H9
boundary. Parse exactly `pinned:<model>`, `max`, `elbow`, `slope:<lambda>`, and
`floor:<n>` for the M1 chat role; leave `MODEL_POLICY_CHAT` unset by default so
the existing `CHAT_MODEL` behaves as a pinned route. Resolve immediately before
the first run in each daemon-lifetime thread, retain one immutable resolution,
and pass that exact model/context pair through `run.started`, snapshots, memory
prepare, ordinary chat, and the tools-free `/remember` label call.

Fetch the Artificial Analysis benchmark and model listings as one cache
snapshot, fresh for strictly less than 24 hours, with a single-flight refresh
and no stale reuse. Use `Decimal` prices normalized from dollars per token to
dollars per million tokens. Implement the specified deterministic Pareto,
signed-log elbow, lower-hull slope, max, floor, and tie rules. A zero-priced
elbow frontier and every other unavailable or degenerate table use the existing
static model/context fail-open. Join a selected benchmark canonical to one
executable model-list route under A-026: prefer its single standard route over
explicit variants, accept a sole variant-only route, and otherwise fail open;
take both request ID and context length from that same row.

Every OpenRouter call carries `session_id=thread_id`. Calls selected by a
non-pinned policy additionally sort providers by price; pinned OpenRouter calls
do not. Provider fallbacks remain at broker defaults. Create fresh per-run model
settings, resolve provider clients lazily from the route actually selected,
cache settings-owned Pydantic model objects by resolved route, and retain
broker cache-read and cache-write token counts through the existing usage
envelope and browser state. An explicit pinned policy therefore does not demand
credentials for an unused static `CHAT_MODEL`. Keep the H8 thread-owned model
display seam; the human model selector remains M2 scope.

**Motivation.** One retained resolution prevents the visible model, memory
budget, chat model, and label model from drifting apart as a conversation
grows. Exact decimal policy math and one timestamped broker snapshot make the
economic choice reproducible, while session stickiness preserves the prompt
prefix whose repeated input cost motivated H9. Binding canonical benchmark data
to a concrete standard route avoids silently opting into free, batch, or
extended semantics and makes context accounting truthful.

**Rejected alternatives.** Floats, epsilons, and silently dropping a free
benchmark row make elbow results irreproducible. Reusing an expired table makes
the 24-hour bound false. Selecting a context independently from the request ID
can overstate the actual route. Opaque classifier routing, quantization filters,
disabled fallbacks, an H9 browser selector, and a second label policy all exceed
or contradict the enacted boundary. Closing provider-owned clients through
private Pydantic internals is also rejected; explicit model ownership remains a
small lifecycle follow-up rather than an H9 shutdown hack.

## 018 — Delegate non-default model strings to Pydantic AI [P3]

**Decision.** Keep explicit, settings-owned provider construction for the
OpenRouter, Anthropic, and OpenAI routes exposed in Harness configuration.
For every other provider prefix, delegate provider construction to Pydantic
AI's installed provider registry and normalize its configuration errors at the
Harness boundary. This supersedes Decision 008's rejection of all other direct
providers. The browser still displays one daemon-resolved model per thread;
this does not add a selector or provider-specific Harness settings.
OpenAI's `openai`, `openai-chat`, and `openai-responses` aliases all remain on
the settings-owned credential path. A registry provider whose optional package
is not installed fails as a normalized configuration error rather than leaking
an import exception.

**Motivation.** C.8 requires the cold-start chat path to accept a Pydantic AI
model string, including local providers. Repeating Pydantic AI's provider
matrix in Harness would drift and violate DRY. The three default hosted routes
retain the stronger settings-owned secret boundary, while opt-in providers use
their upstream configuration contract.

**Rejected alternatives.** Keeping the hard-coded three-provider rejection
contradicts C.8. Adding one Harness setting and constructor per upstream
provider duplicates a registry the adapter already depends on. A browser model
selector is M2 scope and is not needed to prove configuration-level model
agnosticism.

## 019 — Journaled model resolution points and cache epochs [P3, P4, P4.2]

**Decision.** Implement SPEC v2.26's `/model <openrouter-model-string>` as a
daemon-owned direct turn on the existing `prompt.submit` lifecycle. This
supersedes Decision 017 only where it called a thread resolution immutable and
required `session_id=thread_id` for every request. Validate the exact broker
model ID with a fresh OpenRouter `/models` request, independently of the
24-hour benchmark cache; take the executable ID and context window from that
exact row. Unknown, unavailable, and blank targets return a visible no-change
result. A valid already-current target still creates a new epoch: the command
is an explicit resolution point, including when the old and new slugs match.

Reserve and acknowledge the command in the existing FIFO before broker I/O,
then fetch its candidate when the turn starts and commit only during successful
terminalization. A successful commit increments the thread's stickiness epoch,
swaps the model/context pair, clears the cacheable-prefix receipt, writes one
`model_change` event into the process-lifetime transcript journal and
structured daemon log, and puts the new daemon-authoritative model on that
event delta before its text acknowledgement and `run.done`. The command's
earlier `run.started` truthfully carries the model that is still active at turn
start. No model or Spine call occurs, provider message history omits the daemon
command, and reconnect snapshots retain the event. Epoch zero preserves
`session_id=thread_id`; later epochs use
`session_id=<thread_id>:epoch:<n>`, so switching back still creates a fresh
cache identity. The sacrificed-prefix field is the final provider response's
own input-plus-output token footprint from the last successful ordinary turn,
not cumulative multi-request run usage.

**Motivation.** The FIFO transaction makes deliberate changes observable and
reproducible without permitting policy drift, while reusing the H8
`run.started`/snapshot display seam keeps one authority for the visible model.
A fresh model-list lookup makes the new context limit truthful even when the
benchmark service or its cache is stale. Terminal-response accounting records
the prefix that can actually seed the next request without double-counting
tool-loop history.

**Rejected alternatives.** Resolving or mutating when `/model` is submitted can
block its immediate acknowledgement and overtake an active turn. Mutating
inside the model task creates cancellation windows between state change and
journaling. Reusing the benchmark cache does not re-fetch context and couples a
human command to an irrelevant benchmark outage. Letting generic nested events
control the browser header creates a second model authority. A new C.7 command
type, browser registry/selector, persistent M1 journal database, or replaying
`/model` into provider history all exceed the v2.26 repair.

## 020 — Installed-wheel local control plane [P4]

**Decision.** Publish the Harness distribution as `nocturne-ai` at product
version 0.1.0 with console command `nocturne`, and pin its local dependency to
the lockstep `nocturne-spine==0.1.0` wheel. Bundle the committed production web
build inside the Harness wheel and compose the installed app against that path;
the existing `harness dev` command remains the only Node-backed path. Store one
generated local config beneath `NOCTURNE_HOME` (default `~/.nocturne`) at mode
0600, ask only for the OpenRouter key, and generate the Spine token, database
password, and machine identity. Use packaged Compose only for a loopback-bound
pgvector container; call Spine's packaged migration seam, then supervise the
installed Spine and Harness processes in the foreground.

**Motivation.** ADR-019 treats onboarding attention as product cost. One wheel
environment, one private config, and one foreground supervisor reach a browser
without exposing repository layout, Node, Alembic paths, or hand-written env
files. Spine remains the sole owner of its migrations and deployable source.

**Rejected alternatives.** A cloned three-repo workspace is the relay's
implementation shape, not a user interface. Shipping Node or building the SPA
at first run violates the prebuilt-assets contract. Duplicating Spine source or
migration logic in Harness violates DRY; containerizing both Python services
adds image distribution to a local path whose wheels already contain them.

## 021 — Fixed-foundation, state-aware cloud reconciliation [P4]

**Decision.** Implement `nocturne deploy` only for the named D1 foundation:
`n8-memory-palace`, `us-central1`, and `n8-memory-palace-db`. Read-only planning
classifies each exact resource as NOOP, CREATE, permitted monotonic UPDATE,
HUMAN, or BLOCKED; apply re-observes and executes only the lawful forward
actions. A missing ACTIVE billed project or PostgreSQL 16 instance blocks
rather than provisioning. Existing credentials and secret versions are never
rotated on a rerun. Images build locally for linux/amd64 from Spine-owned
packaged source; migrations run separately; the runtime identity receives only
Cloud SQL Client and per-secret access. D2 remains a distinct real-TTY gate:
exact armed state is a no-op, complete absence may enter the existing typed
detach confirmation, and partial or drifted state stops for human recovery.

**Motivation.** ADR-019's idempotence is desired-state convergence, not license
to widen D.2 045. Observing before planning makes dry-run truthful and makes a
second apply inert, while the state split preserves D2's deliberate outage
authority and its fail-closed recovery law.

**Rejected alternatives.** Generic project creation, billing/budget changes,
Cloud SQL instance creation, deletes, broad IAM, Cloud Build, automatic D2
cleanup, and non-interactive breaker confirmation all cross explicit human
boundaries. Treating a partial breaker as fresh would adopt unknown identities,
keys, triggers, or queued destructive messages.

## 022 — Broker responses become synchronous receipt batches [P4]

**Decision.** Capture each new Pydantic AI `ModelResponse` at the existing turn
adapter and translate its nonzero usage into A-027 receipt lines before the turn
returns. Request usage explicitly asks OpenRouter for native accounting. The
run loop's emitter exposes its already-owned run and prompt ULIDs; trusted tool
context supplies principal, machine, agent path, and thread. Ordinary chat is
`purpose=building`, the label completion for `/remember` is
`purpose=remember`, and a successfully created memory id is attached when
available. Provider response id is the request `ref`; request-id detail and the
first receipt ULID are the declared fallbacks.

OpenRouter/OpenAI-style prompt totals subtract reported cache reads and writes
to produce fresh input; direct Anthropic input is already its fresh class and
is not subtracted. Reported reasoning at or below output is split from ordinary
output so quantities do not double-count it. Native aggregate USD is allocated
token-pro-rata with a twelve-decimal exact remainder and marked `allocated`;
one-line cost is `measured`, and missing cost remains NULL. Downstream provider
is preferred over the broker name, while the broker and raw billing details
remain in `meta`. A receipt failure emits a sanitized `spend_unavailable` event
and makes the run terminally fail; there is no async retry queue.

**Motivation.** The adapter is the first common point that sees every tool-loop
response, normalized usage, broker-native cost, and daemon lineage. Recording
there avoids provider-specific HTTP forks and preserves A-020's one broker
seam. Exact aggregate preservation is dollar-true; the allocated basis admits
that token-pro-rata is not a claim about the broker's undisclosed class rates.

**Rejected alternatives.** Run-level cumulative usage loses one-ref-per-request
grain and downstream provider detail. Emitting zero cache rows pads the ledger
with non-purchases. Treating all prompt totals alike double-counts direct
Anthropic cache usage or understates OpenRouter fresh input. Background writes
can lose charged work, and silently continuing after a failed receipt would
make Vitals look healthier than the bill.

## 023 — Retire the closed-M1 regex fence [P4]

**Decision.** Remove the repository pre-commit hook and CI step from Decision
002 now that Garden report 035 has closed M1. The hook encoded M1's forbidden
feature ledger; it is not a general product-correctness check, and several of
those feature families are now expressly scheduled M2 work. Packet scope stays
governed by the current Garden board and focused packet law. Lint, tests,
packaging checks, and contract evidence remain CI gates.

**Motivation.** The closed-milestone regex rejected the enacted M2A spend
contract. Leaving a stale guard in place makes lawful work indistinguishable
from scope drift and invites bypassing a check whose premise no longer holds.

**Rejected alternatives.** `--no-verify` would conceal the mismatch and still
leave CI red. A milestone switch whose M2 branch does nothing is ceremonial
machinery. Rewriting the regex for every packet duplicates Garden authority in
two product repositories and cannot express packet dependencies reliably.

## 024 — One isolated bridge for the first-party rack [P2.5]

**Decision.** The rack host owns the sole Zustand/WebSocket adapter and renders
every first-party surface in a sandboxed iframe on `rack.localhost`, an origin
distinct from the local shell. A transferred `MessagePort` exposes exactly the
versioned event, query-plus-`as_of`, and selection surfaces. The frame manifest
scopes readable C.7 streams and permitted C.7 actions; the host rejects an
undeclared action. Both handshake directions pin the expected local origin, so
a navigated frame cannot impersonate a resident and acquire the bridge. Rack
documents are served with `connect-src 'none'`, no
forms, frames, workers, objects, or media, while the main shell refuses to be
framed. The compiled M2 modules are the only loadable residents; M3 still owns
folder loading, hot reload, the public authoring SDK, and the contributor
skill.

Use a twelve-column, twelve-row host grid. The fixed header consumes one row;
the thread, chat, and memory modules share the remaining eleven. A horizontal
resize clamps the selected manifest bounds and trades whole units with its
adjacent module, preserving a twelve-unit row. Drag/drop or Alt+arrow reorders
the modules. The current layout auto-restores locally, and one explicit saved
set can be restored or replaced; this is the sole currently implemented mode.
`ResizeObserver` rectangles cross the same bridge as resize events. NEO-NOIR
is a token-only default layer over the modules, with one semantic danger color.

**Motivation.** P2.5 exists so the shipped interface is a replaceable factory
opinion without privileged first-party plumbing. An isolated origin makes the
iframe boundary real while still allowing the built assets to load; the CSP
turns “no network egress” into a browser wall. Trading units with a neighbor
keeps the rack constrained and deterministic instead of creating overlap or
hidden overflow. Keeping the bridge serializable gives M3 one delivery seam
instead of a second API.

**Rejected alternatives.** An in-process provider shaped like the future API
would not satisfy ADR-023's sandbox law. Same-origin frames can remove their
own sandbox. Freeform pixel windows violate the grid-unit resize law. Loading
arbitrary plugin folders or inventing parameter bindings in M2B would pull M3
and M2J into this packet.

## 025 — Capture-first local transcript journal [P3]

**Decision.** Write one versioned append-only JSONL per opaque thread beneath
`NOCTURNE_HOME/transcripts`. Capture immutable snapshots when each user or
assistant message is created or terminally updated, and capture every
daemon-authored C.7 run event before live delivery; this includes deltas,
usage, gates, errors, terminal events, and the `/model` `model_change` event.
Every captured message carries ADR-016's `parentId` now, including forward
continuity across daemon restarts. A queued prompt initially names the latest
message that already exists; when its predecessor's assistant row lands, the
prompt is re-journaled with that final parent. Each message row also records
the current logical tail, so a revision to an earlier queued message cannot
move restart continuity backward. M2D reads only that durable tail id for the
next link — it never hydrates messages or changes the process-local snapshot
contract. Snapshot resyncs and panel query replies are serving artifacts
rather than new transcript events and are not copied back into the journal.

Map thread ids to SHA-256 filenames instead of trusting them as paths. Create
the transcript directory and files at modes 0700 and 0600, append with
`O_APPEND`, and `fsync` every complete standard-JSON line before the run
advances. An advisory file lock preserves record boundaries if another local
writer touches a file; conversation scheduling and tail ownership remain the
single daemon's single journal. Roll a failed partial append back to its
starting offset, separate any pre-existing incomplete tail before resuming,
and refuse symlinked or non-regular thread files. Open the transcript root as
a no-follow directory before opening a hashed child, and refuse a root beneath
any git worktree. The initialized home is propagated to both local services so
an overridden `NOCTURNE_HOME` cannot split configuration and conversation
state. Any capture failure poisons the run loop, including work already in
flight: later work is refused instead of continuing with an unjournaled or
half-mutated thread.

**Motivation.** Item 4 requires capture now without importing M3's session
table, tree serving, rewind, or Cube query surface. Self-contained message and
event rows preserve everything needed for that later backfill, while seeding
`parentId` honors ADR-016's first-persistent-store requirement without
activating tree behavior early. Synchronous durable appends make a detached
browser or daemon restart irrelevant to capture and make a write failure loud
instead of silently claiming persistence.

**Rejected alternatives.** Loading JSONL into `thread.snapshot` would pull M3
serving into a capture-only packet. SQLite or a `session_message` table would
pre-build the M3 schema. Logging only WebSocket traffic loses events while no
client is attached; logging resync snapshots duplicates old history. Raw
thread ids permit path traversal. Git storage violates the explicit push-leak
wall, and buffered best-effort writes can lose the exact tail this packet
exists to preserve.

## 026 — Vitals crosses the existing rack query bridge [P2.4, P2.5, P4.1]

**Decision.** Adopt Garden A-028 and its collision repair A-029 as the M2C
surface contract. The owner daemon
uses its existing Spine bearer credential to fetch the live Vitals snapshot,
then exposes that typed response only through ADR-023's public rack query
surface. The sandboxed first-party resident receives neither the credential nor
a private transport and keeps `connect-src 'none'`. Non-now requests remain a
typed `historical_unavailable` result; upstream failures become a sanitized
module-local failure and do not disable Chat.

The daemon's typed Spine mirror rejects a snapshot that omits or duplicates
A-028's gauges, changes their enacted availability status, breaks lane order or
A-029 key identity, moves a sample outside the open trailing-hour window, or
fails exact dollar/receipt/unpriced conservation. Required nullable members
remain required on the wire: absence is not interchangeable with an explicit
honest null.

Render the server-grouped exact-string total, purpose, and model lanes in one
full-width bottom rack strip. JavaScript may map values to SVG coordinates but
does not regroup or sum currency. Collapse reallocates whole grid rows to the
existing panels, mobile starts collapsed, and expanding reflows the rack rather
than overlaying Chat's composer. Click or keyboard activation owns lane focus;
hover and touch scrub publish the selected minute with that focus across the
shared selection surface. Selection is a button and its quantitative timeline
is a separate accessible slider, so keyboard value movement is explicit.
Sparse server buckets remain disconnected rather than inventing a trend across
minutes with no receipts. Deterministic fixture data is intrinsically marked by
its own server identity; a query string on the owner app cannot opt into the
fixture banner.

**Motivation.** Reusing the one declared query and selection bridge proves the
first-party module lives within the same public boundary promised to future
residents. Server-owned grouping preserves dollar truth. A rack-resident strip
keeps spend continuously legible without adding another page or sacrificing
the owner's primary conversation surface on a phone.

**Rejected alternatives.** Giving the iframe a Spine token or network access
breaks the isolation contract. A new plugin loader, SDK, registry, or parameter
system pulls M3/M2J into M2C. Browser-side dollar aggregation creates a second
ledger. A fixed overlay can hide the composer, while a separate dashboard page
would not satisfy the resident-rack requirement.

## 027 — Re-score ordinary messages inside the model/feedback boundary [P1.2, P1.4]

**Decision.** Adopt Garden A-030 as the M2G owner-path contract. Keep one
daemon-lifetime registry per thread for current, human-confirmed, explicitly
excluded, and event-source membership. The first ordinary message still opens
the existing gate; its survivors become confirmed. Every later ordinary
message prepares autonomously while serialized with context-changing panel
feedback, replaces the bound model block from Spine's canonical response, and
publishes an unsolicited authoritative panel refresh only when membership
changes. `/remember` remains its own command path and does not re-score.

Remove moves a current member into the thread exclusion set only after Spine
accepts feedback. Re-add resolves the active current MemoryUnit, records
`mid_thread_added` against the same event source, and restores it as a confirmed
lock. The panel exposes Re-add only for an explicitly thread-excluded item. No
post-first prepare opens a modal; an upstream failure remains visible and fails
open with the prior trusted context.

**Motivation.** One serialized boundary ensures the model never races a human
remove or re-add and receives the exact panel membership the owner sees. Spine
owns scoring and frozen rendering; Harness owns ephemeral conversational state
and presentation. This keeps the authority split narrow and testable.

**Rejected alternatives.** Client-side rescoring duplicates the canonical
scorer and leaks authority into an iframe. Treating removal as a corpus edit
loses its thread-local meaning. Polling the panel adds latency and still races
the model boundary. Persisting thread context in a new Harness database would
pre-build later session infrastructure outside M2G.

## 028 — One thread-owned registry seam for the model device [P2.5, P3, P4]

**Decision.** Adopt Garden A-034. Keep descriptor validation, current values,
daemon-lifetime replay history, named-model resolution, and change/refusal
publication behind one RunLoop-owned parameter boundary. The first-party MODEL
DEVICE reaches it only through the public rack query/action API and declares
all six bindings in its control-plugin manifest. Request parameters live on
the thread's immutable model resolution value and are copied into each fresh
broker settings body; a selector change preserves them while starting the
standing new cache epoch. CURRENT follows shared thread selection. GLOBAL is
an honest read-only registry/default view because M2J ships no global writable
descriptor.

**Motivation.** One owner of model truth prevents the header, registry, and
broker request from drifting apart. Publishing accepted and refused writes as
C.7 events makes controls replayable and lets M2D capture them without turning
the capture journal into the forbidden pre-M3 session server. A read-only
GLOBAL view obeys the rack-wide scope law without fabricating a global
temperature whose effect the product cannot define.

**Rejected alternatives.** Browser-owned values or direct provider writes
would bypass descriptor authority and disappear from the journal. A second
settings store would compete with RunLoop's model resolution. Hydrating
parameter state from transcripts would violate M2D's capture-only fence.
Resurrecting MODEL_INTELLIGENCE_FLOOR would reverse A-021; a global floor control
can exist only if later law binds the current policy grammar to the registry.

## 029 — Memory instruments use the public Rack bridge [P2.4, P2.5, P4]

**Decision.** Adopt Garden A-035. Add Memory Graph and Injection Console as
first-party sandboxed Rack overlays with only the public query, action,
selection, and scope surfaces. The daemon owns Spine credentials and translates
GLOBAL to a null corpus/thread filter and CURRENT to the selected thread's
authoritative committed context. Node selection publishes a memory identity;
the existing Memory Palace editor remains the only edit surface.

The Injection Console binds exactly the eleven enacted scorer descriptors.
“Enact version” creates a new version, while learner proposals use their
distinct activation action. Gate and Palace cards read server-recorded weighted
contributions and say “Not scored yet” when no event exists. Vitals applies the
same persisted GLOBAL/CURRENT scope control and routes CURRENT to thread receipt
lanes.

**Motivation.** Reusing the Rack seams keeps credentials and authority out of
residents, while selection joins graph inspection to the already proven CAS
editor instead of creating competing controls. Exact server contributions keep
the UI explanatory without making it an accountant.

**Rejected alternatives.** A second graph editor violates DRY and CAS
ownership. Three-dimensional rendering, bulk graph actions, and cross-Palace
views are M3. A preview button would claim M2P what-if semantics that M2K does
not enact.

## 030 — Isolate fixtures by reachability; spool receipts beside the journal [P3, P4.1]

**Decision.** Adopt Garden A-038. Give every scenario app the same enforced
identity, product-port refusal, root redirect, verified full-viewport banner,
foreground launcher, and temporary browser-profile contract. The owner app
offers a narrow one-time cleanup only for exact titles generated by the known
pre-M2O fixture prompts; it never guesses from arbitrary title text or clears
the catalog wholesale.

Put failed spend batches in an owner-local atomic receipt spool beneath
`NOCTURNE_HOME`, retaining stable event IDs and replaying oldest-first through
the existing Spine endpoint. The running process retains a memory fallback if
the spool itself is unwritable. The daemon enriches the public Rack Vitals
projection with queue state while leaving Spine's canonical A-028 response and
M2M's dollar reconciliation authority unchanged.

**Motivation.** Reachability—not source-directory intent—is what protects the
owner from a fake, so port refusal and server-verified identity belong at the
fixture boundary. Stable event IDs make a tiny file spool sufficient for
exactly-once replay through A-027. Local queue visibility closes the hours-long
gap before scheduled broker reconciliation without inventing dollar drift.

**Rejected alternatives.** A mock-mode flag would violate B.6 rule 10. Merely
changing README ports leaves an accidentally launched fixture reachable on
8765. Clearing all local storage risks real navigation metadata. A second
database or general job queue is unnecessary for a handful of immutable
receipt batches, and marking the turn failed would preserve the bug M2O exists
to remove.

## 031 — Measure context total; disclose the category estimate [P2.2, P2.5]

**Decision.** Adopt Garden A-039. Record the terminal broker response's
per-request input tokens beside the immutable resolved model context length.
Estimate the four owner-facing categories from the exact memory injection and
owned capability definitions, assigning the broker-total remainder to history.
Expose CURRENT and GLOBAL projections only through the public Rack query seam,
and place the compact CONTEXT BARS module beside Palace Vitals.

The 80% line is presentation only and explicitly says compaction is not active.
M2R does not mutate history, warn, block, or add a context-policy service.

**Motivation.** The broker owns the credible total but does not report a
category split. Separating that measured fact from a plainly labelled estimate
gives the owner useful pressure visibility without false precision or a second
token authority.

**Rejected alternatives.** Calling the cumulative run usage the current
context would overcount multi-request tool turns. Presenting locally counted
categories as provider facts would hide uncertainty. Instrumenting provider
internals or building compaction policy now would exceed the packet and create
machinery M3 owns.

## 032 — Syntax-ratcheted test motivation and inverse law index [P4]

**Decision.** Adopt Garden A-040. Ship a repository-local, standard-library
checker that reads Python test docstrings and JavaScript test JSDoc, accepts
only the enacted citation grammar, and grandfathers only an exact normalized
source digest. Run it from both the local pre-commit configuration and CI.
Generate the law-coverage artifact from the same scan rather than maintaining a
second hand-written index.

**Motivation.** A filename exemption would let an old test change forever
without explaining its purpose. A source digest makes the temporary baseline a
real ratchet, while one scanner keeps enforcement and coverage from disagreeing.

**Rejected alternatives.** Enforcing prose quality with keyword heuristics
would manufacture confidence the machine cannot justify. Sharing the script
through a sibling checkout would break installed and standalone repository
operation. Auto-inserting generic docstrings would disguise the human sweep as
completion.

## 033 — Evolve owner config in place before lifecycle commands [P1.3, P4]

**Decision.** Adopt Garden A-041. Move local config to version 2 by atomically
upgrading a private version-1 file in place, preserving the generated secrets
and adding only bounded backup-generation retention. Pin the packaged Compose
database by its multi-platform OCI index rather than an architecture-specific
manifest.

**Motivation.** Backup and restore cannot be durable if a routine package
upgrade strands the owner's existing config or silently changes the database
image beneath it. The first config transition proves that evolution is a
preserving operation before recovery commands depend on it.

**Rejected alternatives.** Reinitializing would rotate secrets and disconnect
the existing Palace. Treating missing fields as permanent implicit defaults
would leave no versioned migration trail. Pinning one architecture would make
the same wheel behave differently on Apple Silicon and cloud build hosts.

## 034 — One verified local backup authority [P1.3, P4]

**Decision.** Adopt Garden A-042. Stream PostgreSQL's custom archive from the
already-running packaged Compose database into a private temporary generation,
verify it with the matching container's `pg_restore`, record its digest, size,
image, revision, reason, and ULID in one receipt, then atomically publish it.
Manual backup and the local pre-migration path call the same writer; retention
deletes only generations that fully validate against that receipt contract.

**Motivation.** Restore, migration safety, pruning, and doctor need one fact to
trust. A receipt that can be checked without secrets makes the archive
self-describing, while temp-then-rename prevents a crash from promoting a
partial dump. Reusing the pinned database image for dump and verification keeps
the installed wheel free of a second PostgreSQL client toolchain.

**Rejected alternatives.** A raw SQL text dump is larger and less suitable for
side-by-side restore. Installing host `pg_dump` creates version drift. Naming a
directory a backup without verifying its archive would make retention capable
of deleting good history in favor of corrupt output. Deleting unfamiliar files
would turn a bounded product cleanup into broad filesystem authority.

## 035 — Read-only lifecycle doctor with an early disk boundary [P1.3, P4]

**Decision.** Adopt Garden A-043. Add `nocturne doctor` as one read-only local
inspection that measures database, journal, backups, and free space; revalidates
every recognized backup against the existing A-042 authority; and warns at the
greater of 5 GiB or ten percent free. Preserve distinct healthy, warning, and
failed exit statuses.

**Motivation.** Mandatory history can fail closed safely only after the owner had
a useful warning. Rechecking the same receipt, digest, permissions, and archive
format used at publication also keeps backup confidence from becoming a stale
claim.

**Rejected alternatives.** A background notifier would create a new attention
channel before the enacted Deck threshold exists. Automatically deleting data
would turn diagnosis into recovery policy. A second backup parser would let
retention and doctor disagree about which generations are real.

## 036 — Split resource observation at the process boundary [P1.3, P2.4, P4]

**Decision.** Adopt Garden A-044. Let Spine report the database bytes it owns,
then enrich that Vitals object at the Harness Rack boundary with current daemon
RSS, monotonic uptime, and owner-local disk, journal, and backup measurements.
Reuse the same local storage reader for doctor and startup warning.

**Motivation.** A useful resource gauge must be honest about where each number
comes from. Harness cannot infer Cloud SQL size from its local disk, and Spine
cannot observe the owner's daemon process or filesystem. The existing Vitals
enrichment seam is the one place those facts can meet without creating another
monitoring service.

**Rejected alternatives.** Adding psutil for one process number expands the
install surface unnecessarily; the supported host already exposes current RSS
through `ps`. Polling Docker for database volume size would be local-only and
false for the owner's cloud Palace. A popup would violate the passive Vitals
and least-attention law.

## 037 — Switch local restore through one durable volume pointer [P1.3, P4]

**Decision.** Adopt Garden A-045. Make the active PostgreSQL volume a private,
versioned config value. Restore and migrate a candidate volume in isolation,
compute the rollback manifest from both live databases, and change that one
pointer only after the exact backup-bound confirmation. Retain the former
volume with a private rollback receipt.

**Motivation.** Docker volumes cannot be renamed. Copying restored files into
the existing volume would be an in-place replacement wearing a safer name, and
changing Compose project identity would orphan every other lifecycle command.
One constrained pointer makes the switch durable and mechanically reversible.

**Rejected alternatives.** Raw filesystem copying bypasses PostgreSQL's restore
semantics. Reusing the live container cannot prove side-by-side validity.
Deleting the former volume would erase the owner's fastest recovery path, and
keeping candidates after cancellation would accumulate ambiguous Palaces.

## 038 — Prove the provider backup before owner-cloud migration [P1.3, P4]

**Decision.** Adopt Garden A-046. Create one uniquely described Cloud SQL
on-demand backup, capture its operation and backup IDs, wait for that operation,
independently describe the completed backup, and atomically persist the safe
metadata under the owner's private Nocturne home before invoking Alembic.

**Motivation.** Submission is not recoverability. A migration can begin only
after the provider says the exact backup is successful and the owner has a
durable locator that survives terminal output and process exit.

**Rejected alternatives.** Treating the latest scheduled backup as this run's
receipt would not prove ordering. Waiting without describing the backup would
prove only operation completion, not a usable backup object. Automating restore
or pruning cloud backups would expand an evidence seam into destructive cloud
lifecycle authority the packet explicitly does not grant.

## 039 — Keep scorer consequence inside the public Rack bridge [P1.2.3, P2.5]

**Decision.** Adopt Garden A-047 and A-048. The Injection Console uses three
explicit public Rack actions: simulate, exact-receipt force, and read-only
proposal audition. The daemon supplies principal and machine identity behind
that boundary; browser requests cannot claim either. Any knob edit clears the
DEEP receipt, while an audition result may be fanned out inside the host only
as a presentation mark on the live Gate and Memory Panel.

**Motivation.** The owner needs to see consequence before authority changes,
but the browser must not become a second scorer or an identity authority. One
typed bridge keeps credentials and replay in the owned services while allowing
all three existing views to explain the same comparison.

**Rejected alternatives.** A private console fetch would bypass Rack
permissions. Persisting audition overlays would contaminate commit and
feedback. A confirmation dialog would add friction without proving that the
displayed evidence still matches the values being forced.

## 040 — Select the Palace rung in one private config [P4]

**Decision.** Add an explicit local-or-remote Palace mode and Spine origin to
the existing versioned Nocturne config. The installed daemon remains the same
on both rungs. Local mode retains Docker, migrations, Spine, and backup
lifecycle; remote mode verifies the configured Spine and starts only the
packaged daemon. Existing version 3 configs upgrade atomically to explicit
local mode.

**Motivation.** The owner's cloud Palace already works, but reaching it through
a sourced checkout env and a developer command makes the more capable rung
harder to start than the local one. One config lets `init` and `up` remain the
whole startup vocabulary without turning a deployment choice into a second
product.

**Rejected alternatives.** Reading the repository `.env` would preserve the
checkout dependency the packet removes. A second remote-only config format or
command would fork the capability ladder. Starting a local Spine as a proxy
would add an unused service and blur which Palace owns the data.

## 041 — Separate credential custody from schema observation [P1.3, P4]

**Decision.** Represent a migration whose revision could not be queried as
`UNOBSERVED`, never drifted. Under D.2 096, ordinary `nocturne deploy` recognizes
only the exact fixed-owner shape (foundation, database, built-in user, and
managed secret all exact; authentication fails), offers one plain consent, and
then calls the narrow alignment operation inline. That operation first persists
a verified Cloud SQL backup receipt, resets the user through a private flags
file, adds one secret version through stdin, and disables superseded enabled
versions. The same receipt remains bound to the same run's later migration.
After the reset and secret rewrite both succeed, publish a private non-secret
custody receipt in the Nocturne home. Its absence is the one-time alignment
signal; its exact fixed-target fields prevent future software updates from
rotating credentials again.

**Motivation.** Credential disagreement says nothing about `alembic_version`.
Treating it as schema drift hid the real remedy, while teaching every deploy to
reset credentials on broader drift would turn a one-use recovery grant into
standing authority. One enabled secret version gives the runtime an unambiguous
`latest` value without deleting the audit history. Accepting `nocturne up`'s
version prompt passes that consent into deploy so the owner answers once.
Successful authentication alone is not durable proof that this deployer minted
the credential, because the hand-built password happened to remain valid.

**Rejected alternatives.** Adopting an unknown hand-built password cannot prove
custody. Printing or passing the password in argv leaks it. Deleting the old
secret version discards useful history. Rotating on any mismatch could break a
recoverable service during an ordinary dry-run/apply cycle. Asking again inside
deploy after `nocturne up` already received consent would make the promised
one-step update two steps.

## 042 — Isolate registry credentials without hiding Docker routing [P1.3, P4]

**Decision.** Give registry login and Buildx one temporary Docker configuration
that retains only `currentContext`, `cliPluginsExtraDirs`, and links to the
existing Buildx, plugin, and context state. Persistent registry auth,
credential stores, and credential helpers never enter that configuration.
Preflight runs both `docker buildx version` and `docker info` through this exact
environment before an owner-cloud receipt can be minted. A post-custody owner
update still begins with its own fresh verified receipt and preserves the
image → service → migration → authenticated-verification order.

**Motivation.** An empty `DOCKER_CONFIG` protected registry credentials but also
hid Homebrew Buildx and the Colima context. The first exact-path proof therefore
passed in one environment and the real build failed in another after consuming
the receipt. Credential isolation is useful only if the preflight and build see
the same non-secret routing facts. The post-custody ordering remains explicit
because a completed reset must not silently turn a resumed owner update back
into migration-first execution.

**Rejected alternatives.** Copying the whole Docker configuration would copy
persistent registry credentials and helpers into the build sandbox. Logging in
through the owner's persistent configuration and logging out afterward could
erase an existing credential. Invoking a Homebrew plugin path directly would
hard-code one workstation layout and bypass Docker's configured plugin seam.
Treating the consumed receipt as reusable would violate D.2 096/097.

## 043 — Resolve one web build without synthesizing package files [P4]

**Decision.** The packaged factory serves the wheel's private `_web` directory
when it exists. In the canonical editable checkout it instead serves the
existing `web/dist` directly, or invokes the existing web builder once when
Node.js is available. It never copies checkout output into the package tree.
When no build can be materialized, the daemon stays reachable long enough to
return one plain 503 with the remedy, and startup treats that first refusal as
terminal instead of polling it again.

**Motivation.** Hatch creates `_web` only while building a wheel, but the owner
runs the same command from an editable checkout. Both layouts already have one
canonical copy of the same compiled rack; selecting the copy that belongs to
the active layout keeps the two startup paths equivalent. A permanent refusal
is actionable state, not liveness noise, so repeating it spends attention
without adding information.

**Rejected alternatives.** Recreating the gate's hand-copy would leave stale,
ignored package files that can mask a changed canonical build. Rebuilding on
every startup would add needless Node work when either valid build already
exists. Continuing to poll a deterministic 503 would preserve the wall of log
lines and hide the response's exact remedy.

## 044 — Bind immutable releases to source and reuse verified backup custody [P1.3, P4]

**Decision.** Hash the exact packaged Spine build context by relative path,
mode, and bytes. Publish that digest as a companion immutable Artifact Registry
tag on the same image as the semantic version. Observation accepts an existing
version only when its image also owns the expected digest tag; otherwise the
planner refuses until the Spine version is bumped. Rung 2 `nocturne backup`
uses the existing verified Cloud SQL on-demand receipt path with the ambient
human-owner gcloud identity and does not enter deployment discovery or grant
reconciliation. `up` and read-only `doctor` share one daemon dependency
inspector; only `up` may materialize a buildable web app.

**Motivation.** An immutable version tag prevents overwriting bytes but cannot
by itself reveal that local packaged source changed without a version bump. A
digest companion makes that comparison observable before Buildx tries the
forbidden push. The cloud migration path already proves provider completion and
persists private recovery evidence, so using it for an explicit owner backup
keeps one recovery authority. Sharing the startup inspector makes doctor's
promise mechanically cover the same assets, port, and rung-specific toolchain
that startup will use without turning diagnosis into mutation.

**Rejected alternatives.** Rebuilding and comparing image bytes would consume
work before the version guard and would make a dry-run depend on Docker.
Mutable metadata outside the immutable repository could drift away from the
image it describes. A second Cloud SQL backup implementation would duplicate
verification and receipt rules. Letting doctor run npm would violate its
read-only contract, while separate readiness checks would invite parity drift.

## 045 — Annotate mis-stamped decisions without inventing learner state [P1.2.2, P4]

**Decision.** Preserve an explicit evidence annotation for the two M2X seed
decisions stamped `harness-browser`, classifying them under their authoritative
`m2x-sop-verification` session identity. Do not mutate append-only decision
history or add a training-exclusion column. Queue decisions remain outside the
enacted learner input, which is `injection_event`; their floor eligibility is
therefore false by source boundary. The owner API now removes identity from the
browser contract and stamps the daemon's configured identity at the trusted
boundary.

**Motivation.** F023 combined a real provenance defect with an apparent learner
contamination. Fixing the authority inversion prevents recurrence. Recording
the historical classification preserves the scout observation and makes its
intended treatment reviewable if learner inputs expand, while stating the
current source boundary proves the 25-signal floor was never contaminated.

**Rejected alternatives.** Rewriting stored decision provenance would destroy
the observed failure. Adding a database migration or learner exclusion path for
rows the learner never reads would create dormant policy and imply a false
contamination. Leaving only prose in the relay report would make the two exact
records and their classification difficult to audit later.

## 046 — Let rack documents shrink below the owner shell floor [P2.2, P2.4, P2.5]

**Decision.** Keep the owner shell's 320-pixel minimum, but remove that minimum
inside documents loaded as rack modules. At internal module widths of 20rem or
less, stack the Context and Vitals controls, reflow each Vitals lane into a
label/readout row above its scrubber, and retain horizontal scrolling only for
the explicitly bounded gauge rail.

**Motivation.** The rack deliberately assigns Context and Vitals rectangles
narrower than 320 pixels at the 390-pixel owner viewport. Applying the shell's
minimum to each embedded document created a false 320-pixel canvas, causing
both F024 and F025. The module boundary must honor the width the rack actually
owns, while the important facts—the measured context total, explicit category
estimate, and exact dollar readout—remain immediately visible.

**Rejected alternatives.** Hiding overflow would conceal owner truth. Widening
the rack modules would move the overflow disease to the shell. Making every
gauge fit by compressing its long rail would destroy its watchable scale, while
allowing the whole Vitals document to scroll would hide the exact current value.

## 047 — Rebuild current conversation truth from the durable tail [P1, ADR-016]

**Decision.** On daemon construction, scan the private journal files and rebuild
each thread by taking the latest immutable snapshot of every message, then walking
parent links backward from the last durable tail. Refuse startup when that branch
has a gap or cycle. Restore completed ordinary user/assistant text pairs as model
recency; keep `/model`, `/remember`, failed turns, gates, and active-run state out
of reconstructed provider history. Re-resolve the last journaled model through the
normal named-model boundary before the next run.

**Motivation.** F030 showed that durable bytes alone did not preserve a usable
conversation: restart rendered the transcript empty and the next model turn had no
past. The journal already records a branch tail and repeated immutable snapshots,
so replaying that structure restores the exact readable branch without making the
browser cache authoritative. Completed plain text is the smallest honest provider
history available in the existing journal; local controls deliberately never
entered provider history before restart either.

**Rejected alternatives.** Treating file order as the transcript would surface
every intermediate snapshot and non-tail revision. Restoring an active run or gate
would invent live work after process death. Replaying control turns into the model
would change their established semantics. Expanding the journal format to serialize
opaque provider internals would not repair the owner's existing files and belongs
to a separate migration, not M2Z1.

## 048 — Stop a similar split without inventing a force path [P1.5]

**Decision.** When an atomic `/remember` split finds a near-similar existing
memory, say that none of the family was saved, identify the first existing
memory, and give the only complete retry path: review or update that memory as
needed, remove its already-covered claim from the source, then remember the
remaining facts. Never reuse the ordinary create copy that offers `force=true`;
the split operation deliberately exposes no force switch.

**Motivation.** A near-similar response is neither a successful family nor an
invalid semantic draft. Atomicity means Harness cannot quietly keep the other
children, while telling the owner merely to update and retry would turn the
same child into a hard duplicate. Naming the overlap and the source edit keeps
the no-write result honest and leaves the owner a path that can actually pass.

**Rejected alternatives.** Adding force to the family would reopen A-049's
enacted request contract and let one override hide overlap across a whole
batch. Reusing the single-create renderer would advertise a control that does
not exist. Returning the generic split guidance would falsely imply that the
model could not preserve meaning and conceal the real similarity decision.

## 049 — Define standalone at the candidate boundary [P1.5]

**Decision.** Tell the semantic splitter that a reference resolved inside the
same candidate remains independently comprehensible, and that source-order
markers such as First, Second, and Third do not make an otherwise independent
fact unsafe. State the witness mechanics literally: instruction-only text must
remain byte-for-byte in operation coverage even though it is excluded from
candidate bodies, while any durable ordinal marker must remain byte-for-byte
in its candidate body. State the enacted 64-code-point label and 128-token body
limits in the model instruction instead of referring to limits that were never
actually supplied. Put the same label and nonblank-coverage constraints on the
structured-output schema, where providers receive them beside the fields they
govern. Describe labels as short retrieval handles (prefer 2-5 words and under
40 characters) while retaining 64 as the hard law. Keep the exact extractive
witness, limits, and
deterministic validator unchanged.

**Motivation.** The M2Z2 recovery replayed its checked-in three-fact source
through two real OpenRouter models. Both returned the safe no-write outcome
because the prompt's bare "stand alone" phrase encouraged them to reject
ordinary local anaphora such as "the ledger ... its purpose" and "the eastern
shelf ... returned there." That conservatism prevented the guided split the
exit criterion exists to prove even though each antecedent lives in the same
candidate. A diagnostic full-model draft then found the three correct facts
but omitted the operation-only head/tail from coverage and removed ordinal
markers from candidate bodies; the unchanged validator correctly rejected it.
The same draft also emitted labels beyond 64 code points, exposing that the
instruction never stated A-049's literal configured bounds. The verification
dossier's ordinal markers were structural rather than durable meaning, so its
checked-in source now expresses the same three claims without them; this keeps
the proof focused on semantic splitting and exact qualifier retention.
Another diagnostic preserved all source bytes but emitted separator spaces as
standalone coverage rows despite the prose prohibition. Schema-local wording
closes that provider-facing ambiguity without accepting a response A-050 says
to reject.
Because a later draft then omitted those boundary spaces entirely, the schema
also names leading and trailing whitespace as source text and gives the literal
`. ` boundary example. This remains instruction at the model boundary; the
validator still accepts only byte-exact reconstruction.

**Rejected alternatives.** Weakening validation would trade visible refusal
for silent meaning loss. Rewriting bodies would violate A-050's exact witness.
Changing the verification paragraph would evade the product boundary instead
of fixing it. Model-specific retries would add cost and nondeterminism while
leaving the shared instruction ambiguous.

## 050 — Converge every seed entrance at the daemon boundary [P1.4, ADR-019]

**Decision.** File choice, drag/drop, pasted files, pasted text, and the
`nocturne seed` command all mint ordinary seed-upload requests and converge on
the existing daemon `/v1/seeds` endpoint. Pasted text becomes a named Markdown
document; the CLI expands path patterns but performs only cheap local format
checks before calling the daemon. None of these entrances decides a batch.

**Motivation.** M2Y5 exists because the native file dialog is not operable by
agents and is unnecessary friction for humans. The durable split, dedup,
idempotency, and consent rules already live behind one daemon operation, so a
new transport should only deliver Markdown to that authority.

**Rejected alternatives.** Running splitters inside the CLI would create a
second pipeline and require credentials there. Auto-approving CLI documents
would violate corpus-born explicit consent. A global paste listener would
steal ordinary chat text; paste is accepted only while the visible seed target
has focus.

## 051 — Measure reviewed normative-bearing headings, not prose tone [P4]

**Decision.** Classify every current SPEC/ADR catalog heading through one
exhaustive reviewed registry as CONTRACT, RULE, MIXED_GUARDRAIL, or
REFERENCE_ONLY. The first three classes form a heading-level coverage
denominator; the report keeps contextual references and all test-to-statute
mention links visible outside that denominator. `D.2` is reference-only for
this measurement because the citation grammar collapses accepted and proposed
rows into one heading token. Any new, removed, or invalidly classified heading
fails the ordinary motivation check until the registry is consciously updated.

**Motivation.** SPEC B.6 rule 12 asks which executable tests defend law, while
SPEC 1.4 deliberately gives contracts, guidance, and horizon guardrails
different force. A reviewed heading inventory makes that denominator
reproducible and exposes its granularity without pretending that one heading
citation proves every clause beneath it.

**Rejected alternatives.** Inferring force from `MUST`, `NEVER`, or
`FORBIDDEN` would elevate examples, rejected alternatives, and historical
prose while missing contracts written without modal words. Calling the result
clause coverage would manufacture precision the current citation grammar does
not contain. Treating all accepted `D.2` history as one covered law would hide
the exact-row ambiguity rather than resolve it.

## 052 — Bind each thread to one artificial project path [P1, ADR-005, ADR-023; PROVISIONAL-TASTE]

**Decision.** Treat a project as a canonical relative POSIX artificial path of
at most 256 Unicode code points. Paths are nonblank, use forward slashes, and
contain neither empty nor `.` or `..` segments; slash-prefix ancestry makes
`build-test/api` a descendant of `build-test` without a second project
database. Seed `build-test` as the first usable path.

Bind each thread to its project once, durably, by appending a `thread_context`
row to that thread's existing transcript journal before exposing the binding.
Hydrate the same identity on restart and never rebind a thread: a project jump
selects the newest thread already in that project or creates another thread.
Legacy journals without a binding retain `None`; the owner surface renders
that state separately as **Unscoped**, never as a project value, wildcard, or
global match.

Carry the daemon-owned binding through project-scoped saves and both first-turn
and autonomous injection preparation. Expose each memory's project provenance
in the Graph inspector, but leave A-035 unchanged: Graph CURRENT is still the
set of injected memory ids, not a project-filtered query. **PROVISIONAL-TASTE:**
place one compact Project path control beside Model in the Active Channel
header, with the separate Unscoped status visible; the owner may overrule that
placement or feel at the M2X gate.

**Motivation.** F028 showed that constructing the owner app with
`project_key=None` collapses distinct work into one undifferentiated Palace and
makes `f_proj` impossible to prove. Thread identity is already the durable
boundary for conversation continuity, so journal-backed project identity keeps
the browser a navigation surface rather than an authority and survives daemon
restart without a new store. Artificial slash ancestry prefigures ADR-023's M3
movement law: a future agent location can become the project without migrating
opaque ids. The bounded shared grammar prevents wire drift, while an explicit
legacy state preserves what old journals actually know. The header control is
the smallest visible intervention at the point where the owner is already
choosing a thread and model.

**Rejected alternatives.** Browser-only or local-storage project state would
drift from the daemon and disappear across restart. Rebinding an existing
thread would mix durable conversation and memory provenance. A project table,
second database, or prebuilt tree browser would duplicate the journal and pull
M3 forward. Absolute filesystem paths or the daemon's working directory would
confuse artificial location with one machine's layout. Treating `None` as a
global project match would leak scoped memory, while placing the word
`Unscoped` in the editable path value would collide with a valid path. Changing
Graph CURRENT to mean current project would silently replace A-035's injected-
membership contract. A separate project screen or permanent sidebar would add
navigation before owner use has earned it.

## 053 — Give one learning truth two cockpit scales [ADR-005, ADR-009, A-051; PROVISIONAL-TASTE]

**Decision.** Consume the scorer console's one server-authored learning view in
two densities. Vitals gets an always-legible authentic-signal and right/wrong
scoreboard with a compact held-out generation trace. The Injection Console gets
the full scoreboard, live-agreement and generation series on one fixed
0–100-percent timeline, and server-authored activation, force-values, and
retrain annotations. Plot coordinates may convert exact percentage strings to
numbers for SVG geometry; labels always retain the server strings, and the
browser never classifies a disposition or calculates a score.

Place the sole **FORCE RETRAIN** control beside authentic learning status, while
the evidence-backed manual scorer control reads **Force values**. A background
proposal enters as a distinct card carrying its held-out measurement and the
existing **Audition** and **Activate** acts. Poll the scorer console every five
seconds while the Console is mounted so proposals arrive without reopening it,
but treat a poll as a quiet telemetry refresh: preserve the owner's draft,
preview, exact DEEP receipt, and audition unless scope is explicitly reloaded or
the active scorer version changes. The server remains responsible for rejecting
a receipt invalidated by changed evidence.

Keep already-polluted fixture catalogs cleanable by recognizing the retired
title through a stable migration fingerprint, and mask that one title as
**Verification thread** wherever catalog titles render. The retired phrase is
therefore absent from the shipped bundle without abandoning old local data.
**PROVISIONAL-TASTE:** the information density, cyan/pink series treatment,
annotation chips, five-second refresh interval, and proposal-card placement are
composition choices for owner evaluation, not new contract law.

**Motivation.** A-051 deliberately creates one read model so Vitals and the
Console cannot disagree. Reusing one presentation model at two scales keeps the
everyday strip glanceable while leaving investigation detail in the instrument
that already owns scorer control. Separating retraining from forcing values
removes a dangerous naming collision, and quiet polling makes background work
visible without stealing the controls currently under the owner's hand.

**Rejected alternatives.** Recomputing agreement or floor progress in React
would create a second learner. Resetting controls on every poll would erase
work merely because a proposal arrived. Putting retrain in Vitals as well would
create a second visible act. Auto-activating a proposal would bypass audition
and human promotion. Deleting the old fixture-title literal without migration
recognition would strand the exact catalogs the cleanup affordance exists to
repair, while continuing to render it would leave the customer-visible leak in
place.

## 054 — Journal one image once, then move compact references [P3, ADR-019, C.7, A-052]

**Decision.** Accept exactly one bounded local image on an ordinary chat turn,
as enacted by A-052, rather than introducing a generic upload abstraction. The
daemon validates the bytes, writes them once as an immutable attachment record
in the existing append-only conversation journal, and binds the user message to
that record. Later message revisions, thread snapshots, queue views, and Rack
broadcasts carry only the attachment identity, media type, byte count, and
SHA-256 digest. The browser renders the attachment through a daemon-owned,
same-origin URL backed by that journal record; the URL is a view over journal
authority, never a second copy or store. The accepted turn sends those exact
validated bytes; restart reopens the journal bytes to reconstruct the same
image content part.

Authorize that broker send only when the current thread's resolved OpenRouter
catalog row positively lists `image` in its input modalities. A known
non-image route or missing capability evidence completes as a normal durable
assistant refusal with the model-switch remedy and no provider attempt. Images
attached to `/model` or `/remember` also refuse normally: model switching must
happen first, and image memory is outside this rung. Transcript extraction sees
the attachment's compact metadata only, never its bytes or an inferred image
description.

**Motivation.** ADR-019's first multimodal rung exists so the owner can paste a
screenshot and have the active agent review it. C.7 makes snapshots
authoritative and the journal makes history mandatory, but copying base64 into
every evolving message and Rack snapshot would turn one bounded owner action
into repeated disk, memory, and WebSocket amplification. One immutable byte
record preserves exactly what was sent across restart; compact digest-bearing
references preserve visible identity and integrity everywhere the conversation
is projected. Catalog-positive capability prevents a silent drop or a paid
provider failure, while a durable local refusal leaves an honest transcript
and a concrete recovery path. Keeping extraction metadata-only prevents input
passthrough from accidentally becoming multimodal memory or a second paid
vision pass.

**Non-goals.** This decision does not create remote-URL ingestion, multiple
attachments, arbitrary file uploads, an object store, image output, image
memory or embeddings, OCR, transcoding, or multimodal extraction. It does not
change model selection policy beyond retaining the catalog capability required
by A-052.

**Rejected alternatives.** Inline base64 in every snapshot would satisfy
literal availability by repeatedly broadcasting and journaling the same large
value. Keeping only a browser Blob would lose the image on restart and make the
browser, not the mandatory journal, authoritative. Sending first and learning
capability from provider success or failure would spend money, produce opaque
errors, and make refusal nondeterministic. A generic uploader or external
object store would add lifecycle, authorization, cleanup, and distribution
problems that one local image-input rung does not have.

## 055 — Preserve the provider's refusal, not a guessed failure [P2.2, C.7, A-054]

**Decision.** Carry a structured provider HTTP failure from the model adapter
through `TurnOutcome` and terminal `run.done`, and record the same bounded
detail as a durable assistant event. Classify a context ceiling only from an
explicit provider code or narrow context/token-limit wording. That class gets
one plain archive-and-continue sentence. Other provider HTTP failures retain
the provider's normalized words and a retry-or-switch remedy. Exceptions that
are not structured provider HTTP failures keep the existing generic runtime
error semantics.

Keep Context Bars on its existing last-successful-response authority. A failed
request has no new measured usage and therefore cannot replace that
observation with zero. No retry is introduced at either the adapter or run-loop
layer.

**Motivation.** F034 showed that the provider's only useful diagnostic was
discarded exactly when the owner needed it, while the last honest pressure
measurement vanished with it. The adapter is the one place that still has the
typed provider exception; preserving it there prevents both browser inference
and generic error copy from erasing the remedy.

**Rejected alternatives.** Parsing arbitrary assistant text in React would
make the browser classify provider behavior. Calling every exception a
provider refusal would hide product bugs. Treating any mention of `context` as
a ceiling would create false guidance. Retrying could duplicate spend and does
not make an overfull thread smaller. Resetting the gauge to zero would invent a
measurement, while adding compaction or automatic archiving would pull M3 into
this bounded repair.

## 056 — Project text is a draft; the daemon binding is the view [P2.5, ADR-023 clause 5, F035]

**Decision.** Keep the Project control's local text only while the owner edits
or while a submitted project jump awaits its authoritative thread snapshot.
When that snapshot settles—or the selected thread or daemon project changes—
derive the rendered value from the daemon-owned binding and discard the local
draft. Apply the same projection after acceptance, refusal, reload, and thread
switch; the control does not infer success from dispatch completion.

**Motivation.** A project dispatch completes when navigation starts, before the
daemon accepts or refuses the requested binding. Treating that dispatch as an
acknowledgement can leave one visible Project name pointing somewhere other
than the journal, injection, and every CURRENT module. A small reconciliation
state keeps typing responsive while restoring ADR-023's one-selection law at
the only boundary that knows the accepted value: the authoritative snapshot.

**Rejected alternatives.** Remounting the control from a React key hides some
state transitions but does not model daemon acknowledgement. Making the local
catalog or text field authoritative would duplicate the journal's project
truth. Rebinding threads, adding a project database, or weakening scoped
isolation would solve a display race by changing the product's data model.

## 057 — Reserve one cross-frame lane; audit rendered boxes [P2.5, M2UX1]

**Decision.** The Header module reserves an inert grid lane for the Rack host's
Save, Restore, and Factory controls. The host overlay occupies that same lane;
neither side guesses around the other with an unowned margin. At phone widths
both the reserve and the desktop controls disappear together. Thread titles
wrap to their full height, including unbroken identifiers, instead of being
line-clamped. The deliberately bounded prompt-derived title ends at its last
complete word before the ellipsis instead of cutting through that word.
Every ordinary Rack drawer begins below the live Header; the memory Gate alone
retains its intentional modal cover. Programmatic file inputs stay outside the
visual and keyboard geometry while their visible chooser owns activation.
Graph labels remain visible and named by SVG title, but sit outside the node's
interactive hit box so adjacent labels cannot create ambiguous click regions.
The phone drawer already fills its entire available stage and owns a visible
Close action, so its fully occluded host scrim is removed instead of leaving an
unreachable button beneath every drawer action.

The standing mechanical audit uses one shared rectangle rule at the exact
390-to-1920 viewport ladder. Its rendered driver translates interactive boxes
from each sandboxed module into host coordinates before testing positive-area
overlap, so a host control colliding with an iframe button cannot hide behind
the isolation boundary. Visible text nodes fail when their horizontal scroll
box exceeds their visible box; intentional screen-reader-only labels are
outside visual geometry. SVG text uses its rendered bounding box rather than
HTML scroll metrics, whose values are incommensurate under a viewBox. Pure
geometry and source invariants remain in the ordinary
unit suite; the browser driver is the real-layout proof because CI cannot
truthfully synthesize browser geometry.

**Motivation.** M2UX1's two owner-visible defects share one cause: layout
ownership stopped at an iframe edge, while tests stopped at source structure.
One reserved lane fixes the ownership error; one translated-coordinate audit
turns that class of failure into evidence across the entire Rack.

**Rejected alternatives.** Moving the floating controls to another guessed
offset merely changes which header action they can cover. A tooltip would leave
thread words visibly missing. Per-module collision checks cannot see a host
overlay cover iframe content. Making the default unit suite launch a system
browser would turn an environment dependency into false red ground; keeping
the pure rule there and the executable browser sweep beside it preserves both
speed and rendered truth.

## 058 — The Rack host owns the way back to the stage [P2.5, ADR-021, M2UX2]

**Decision.** Every dismissible full-screen Rack module is rendered inside one
host-owned shell with one visible **Back to stage** action. Thread End, Palace
Queue, Model Device, Memory Graph, and Injection Console inherit that shell;
the modules do not each invent their own close control. The memory Gate is
excluded because its explicit Continue/Stop decision is the governing hard
pause, while the phone Threads and Memory surfaces keep their existing visible
Back actions.

The thread catalog exposes **Archive** on each row. That action carries the
row's exact thread identity into the existing `/v1/threads/{thread_id}/archive`
endpoint, selects that thread in the ordinary client state when necessary, and
opens the existing Thread End extraction review. It does not delete the
catalog row or create a second archive lifecycle.

**Motivation.** The owner finding was not five unrelated missing buttons. The
Rack host could replace the stage with a full-screen child without retaining a
route home, so every new overlay could repeat the dead end. Owning the return
path at the same layer that owns the overlay makes reachability structural.
Thread lifecycle had the same shape: the extraction/archive behavior already
existed, but the catalog did not expose it where the owner chooses a thread.

**Rejected alternatives.** Adding a different close button inside each iframe
would duplicate policy and let future modules regress independently. Making the
Header's active launcher the only toggle would hide the remedy behind a control
whose meaning changes by view. Deleting or hiding archived rows would add a new
retention policy that the owner did not ask for. A separate archive endpoint or
queue would fork ADR-021's existing consent and extraction path.

## 059 — One template governs every composable stage module [P2.5, ADR-023, M2UX3]

**Decision.** Channel Stack, Active Channel, Memory Palace, Palace Vitals, and
Context Bars are the complete set of modules simultaneously composed in the
constrained stage grid. They all inherit one host frame: title-chrome pointer
drag with iframe-safe capture, keyboard dock movement, manifest-bounded whole-
grid-unit resizing, visible edge and corner handles with directional cursors,
resize telemetry, and persisted order and geometry. A conformance assertion
enumerates that set against the production manifests and refuses a missing
module, a non-movable module, invalid bounds, or a frame family without both an
edge and a corner affordance.

The current grid retains its two layout bands: panels trade width with panels,
and the two instrument strips trade width with each other while their shared
boundary trades height with the panels. This makes Palace Vitals genuinely
movable and two-axis resizable without inventing empty cells or freeform
coordinates. Full-screen modules retain Decision 058's host-owned lifecycle,
and the memory Gate retains its governing hard pause; neither is presented as a
floating stage module. The Header remains the fixed host rail that owns those
launch and layout controls. M3 still owns the zoomable infinite canvas where
all module families can move through arbitrary stage coordinates.

**Motivation.** The owner-observed failures—grabs dying at iframe boundaries,
invisible single-axis resize, and fixed Vitals/Context Bars—came from separate
handling paths, not from module internals. One host template fixes that seam
once and gives later UI packets a stable boundary. Keeping docking inside the
existing grid answers the M2 defect while preserving the explicit M3 horizon.

**Rejected alternatives.** Merely marking the old strips draggable would leave
two chrome systems and the iframe crossing failure intact. Treating collapse as
resize would still provide no chosen grid geometry. Giving every overlay fake
drag handles would imply movement that a full-screen lifecycle cannot honor.
Adding free x/y positions, gaps, zoom, or cross-band floating now would smuggle
the Infinite Stage into M2UX3 and make this repair much larger than its proof.

## 060 — One literal seam carries three complete faces [P2, ADR-018, M2UX4]

**Decision.** The exact Cobalt Seraph plate named by Garden is copied into the
web source tree and reduced by one deterministic, standard-library extractor:
seeded weighted OKLab k-means plus explicit accent masks, a percentile chrome
ramp, and a checked-in part-to-material map. Generated JSON and CSS are build
inputs, and normal generation is a byte-for-byte drift check. The plate hash,
dimensions, seed, cluster count, and generated outputs are pinned by tests.

Every raw color literal formerly present in `base.css`, `shell.css`, and
`rack.css` now crosses one generated token seam. NEO-NOIR preserves those
literal values exactly. SERAPH DRESSED and GOLD LINES supply complete alternate
values for the same seam: the frozen R4A/R5B pairs are exact, while later Rack
colors absent from those auditions use a deterministic semantic-family map.
Theme choice is presentation state under the separate
`nocturne.theme.v1` local-storage key. It is neither a Rack layout parameter nor
an entry in the server-owned parameter registry. Sandboxed module frames receive
the closed theme name as a query parameter; this conveys no new bridge action.

The packet's previously undefined "dataviz six checks" means six mechanical
palette assertions for each complete face: ink contrast, muted-text contrast,
fleet-to-ground contrast, semantic-pair separation, deuteranopia-projected pair
separation, and exactly one danger family. Retained rendered evidence adds three
orthogonal checks: unchanged NEO pixels outside the new control and volatile
fixture rows, palette-family distance from the plate, and a bimodal chrome rim.
The emulation distance ceiling is 0.395, recorded from the first honest retained
Rack render before closeout; it is a regression bound, not a claim that a flat
UI can reproduce the plate's photographed material distribution.

SERAPH DRESSED applies the two-sky wash and viewport-fixed banded chrome only to
the ambient field and module rims. Idle rims stay one pixel, hover/focus may
blaze to two, and interactive fills remain dark. GOLD LINES remains a separate
day face. NEO-NOIR is the worn default. The responsive host reserves a dedicated
theme-control lane, including a separate row at phone width.

**Motivation.** Three usable faces fail as a product if each stylesheet owns a
private approximation of the UI. A single literal seam makes selection complete
across the host and every sandboxed module, preserves the worn skin exactly, and
turns later color additions into a visible build failure. The extractor makes
the reference plate provenance reproducible instead of relying on hand-picked
swatches, while the material rules keep the most visually aggressive face from
turning every control into chrome.

**Rejected alternatives.** Three forked stylesheets would drift at every new
module. Runtime image sampling would make startup and screenshots nondeterministic.
Copying the plate as a background would imitate subject matter rather than
material grammar. A generic theme marketplace, user-authored tokens, server
storage, or Rack-manifest parameter would add product surface with no M2 need.
Applying chrome to panel fills would erase hierarchy and violate the plate's
rare-shine law.

## 061 — The startup matrix characterizes the real command [P4, SPEC D.2 112]

**Decision.** Keep the lifecycle matrix as an exhaustive table-driven test of
the real `up_nocturne` entrypoint, with each physical dimension supplied
through its existing authority: daemon preflight for assets and port state,
the journal preflight for writability, the authenticated API-contract relation
for Palace skew, and the exact read-only deploy path for the release guard.
Only released/pass and development-drifted/block guard pairs are reachable;
the matrix asserts the inverse pairs are impossible instead of inventing a
second source-state detector. Clean-room and host rows must produce the same
voice and action.

**Motivation.** The incidents behind M2LC were not independent bugs. Startup
made sequential decisions from partial state, so a later authority could
contradict an earlier offer. Exercising the actual command keeps one behavioral
authority while the independent expected table makes every combination and
precedence explicit. Reusing the deploy dry-run makes the prompt and guard one
mind without copying immutable-release logic into onboarding.

**Rejected alternatives.** A second product state machine would duplicate the
existing port, asset, journal, contract, and deploy authorities. Hashing source
inside onboarding would create a second release guard. Listing only the seven
historical rows would regress the next unanticipated combination; the full
Cartesian table is cheap and is the point of the packet.

## 062 — Startup asks two bounded questions, not for a deployment plan [P4, SPEC D.2 112, M2LC2]

**Decision.** Before an older or legacy remote Palace may produce an update
offer, `nocturne up` reads exactly two external facts: one authenticated
`/health` response for API-contract compatibility and one Artifact Registry
image listing for the existing immutable version/source guard. The registry
result is classified by the deploy backend's existing image-tag authority; the
onboarding path does not reproduce source hashing or tag semantics. The full
20-stage dry-run remains the operator's deployment diagnostic and begins only
after an affirmative update choice enters the normal deploy command.

Remote startup prints `Checking your Palace — a few seconds…` and flushes it
before either potentially slow fact. The health request has a four-second
boundary and the registry command has a six-second boundary calibrated against
the real warmed CLI; an unreadable guard refuses with the full
dry-run remedy and never prompts. The lifecycle matrix records the first
owner-visible line and the two-second speaking budget for every reachable row,
and names the silent-preflight incident explicitly.

**Motivation.** Compatibility and immutable-source drift are the only facts
that decide whether the prompt itself is truthful. Asking the whole cloud
topology to answer that small question made ordinary startup inherit SQL, IAM,
Secret Manager, billing, Cloud Run, Docker, and network latency it did not need,
turning a safety check into minutes of unexplained silence.

**Rejected alternatives.** Keeping the full dry-run and adding a spinner would
only narrate disproportionate work. Copying source-tag logic into onboarding
would split the release authority again. Running the full observation in a
background thread would still spend resources the startup decision does not
need and create cancellation races. Removing the guard would revive the exact
prompt-then-refusal dead end M2LC fixed.

## 063 — One persistent camera model replaces the screen-sized Rack [P2, ADR-023, M2ST1]

**Decision.** The host stores a version-2 Stage set whose unit is
layer → camera → module rectangles. Every layer has its own pan offset and zoom;
every module keeps integer grid-unit x/y/width/height coordinates on a 32×22
canvas. The existing Rack manifests, sandboxed frames, public plugin surfaces,
scope state, and grid-unit bounds remain the only module authorities. The old
version-1 docked layout migrates into the Work layer once; new factory state
adds Graph and Injection layers whose Memory Graph and Injection Console are
ordinary framed modules, not host overlays.

Removing a module moves its complete rectangle into that layer's library.
Removing a layer moves its complete camera, active rectangles, and removed
rectangles into the same library. Recall restores the retained state, and a
compact off-screen list recenters the camera without moving the module. If the
last visible layer is removed, the host creates one empty replacement canvas so
the library remains reachable. Save, Restore, Factory, and local persistence
operate on the complete Stage set.

The factory cameras, 0.25–1.6 zoom range, background-drag/trackpad feel, layer
bar placement, and initial module composition are **PROVISIONAL-TASTE** for the
next owner pass. Mechanical behavior—one model, layer-local persistence,
grid-unit geometry, exact recovery, and no fixed Graph/Injection tabs—is not
provisional.

**Motivation.** The previous host made every resize trade pixels with a
neighbor because its entire world was one viewport. That caused layout work to
be a zero-sum fight and made off-screen placement impossible. A camera over a
larger coordinate space removes the false scarcity while preserving the Rack's
existing module and plugin contracts. Retaining removed state makes “everything
removable” safe instead of turning customization into deletion.

**Rejected alternatives.** Scaling each old tab independently would preserve
three page shells instead of creating layers. A second freeform plugin registry
would duplicate ADR-023. CSS-only transforms without a persisted camera would
reset on every switch and reload. Deleting removed modules or layers and
recreating factory defaults would lose owner layout. Infinite coordinates,
overlap resolution, minimaps, arbitrary layer creation, and collaborative
layouts are not needed for this packet.

## 064 — Exact values stay authoritative; human numbers are a shared projection [P2.3, P2.4, M2ST3]

**Decision.** The browser keeps exact decimal strings and measured values at
the transport, snapshot, geometry, receipt, and inspector seams. A single
presentation utility projects ordinary rack copy into human numbers: money is
cents at or above one cent and three significant digits below one cent;
percentages and measured quantities use one decimal; token counts use compact
notation. Missing gauges render one em dash in a narrower cell with the reason
in the native tooltip. The production manifest names the former Palace Vitals
module **Spend**; its internal IDs and ledger contracts do not change.

Memory Graph labels are a lossy visual index over lossless node titles and the
inspector. Selected, current-context, and pinned nodes outrank injection count;
labels are shortened, placed inside the viewbox, and admitted only when their
estimated boxes do not collide. Hidden labels retain the node's complete SVG
`title`, keyboard target, selection identity, and inspector text.

**Motivation.** Raw accounting precision made P2.4 less truthful in practice:
the owner could not distinguish the important number from its serialization.
Long missing-state prose consumed the same width as observations, and colliding
Graph labels hid P2.3's meaning. One projection prevents each module from
inventing its own rounding while leaving the durable truth available where
precision changes a decision.

**Rejected alternatives.** Rounding the API or ledger would destroy evidence.
Keeping exact strings in every glance surface would preserve bytes while
discarding comprehension. Hiding every Graph label would avoid collisions by
removing meaning; rendering all labels smaller would repeat the same failure at
a different scale. A dynamic canvas text engine is unnecessary for the current
deterministic grid and would expand M2ST3 into the M3 Graph rework.

## 065 — A pressed colorway is one local data record projected through the existing theme seam [P2.5, ADR-018, M2UX5]

**Decision.** The file picker runs the ratified deterministic extraction in the
host browser, hashes the original image bytes for identity, and samples at most
a 512-pixel long edge before clustering so large plates cannot stall the Rack.
The result is one versioned local record: clusters and their area shares,
accent and percentile evidence, raw-to-worn repairs, validation results, and
CSS custom-property values. Only PNG, JPEG, and WebP input is admitted. Stored
token names and values cross a narrow data grammar; executable CSS forms fail
closed when reloaded.

The existing theme selector remains the one control. A valid record joins it
under `PLATE <hash>` and can be removed there. The host sends that same record
through the existing structured-clone Rack bridge so sandboxed module frames
wear the colorway without gaining file or storage access. Fonts, data
encodings, plugin manifests, and module behavior remain outside the record.

**Motivation.** The owner wants the audition recipe to become a zero-ceremony
personal colorway feature. One inspectable data object preserves the proof of
how the picture became a palette while keeping ADR-018's code boundary real.
Bounded sampling protects the glance surface; reusing the selector and bridge
keeps persistence, removal, and module propagation in one theme path.

**Rejected alternatives.** Persisting the source image would retain private
material the feature does not need. Generating a stylesheet or accepting
arbitrary CSS would turn user input into code. A second colorway panel or a
second iframe storage protocol would duplicate the theme authority. Server-side
or LLM extraction would add latency, spend, and private-image movement to a
fully deterministic local operation.

## 066 — Rare choices belong to one host setting surface; module gears expose only real actions [P2, ADR-023, M2ST2]

**Decision.** One gear beside the Nocturne identity owns app-level choices that
do not help with the immediate work: the existing theme selector, local plate
pressing, and Stage Save/Restore/Factory actions. The work toolbar keeps only
layer, camera, and library controls. Every ordinary module frame and
dismissible full-screen module gets the same host-owned settings slot.

That slot offers Palace/thread scope only when the module manifest declares the
existing `rack.scope.set` action. Choosing a scope dispatches that action and
remounts the sandboxed frame at the persisted scope. A fixed-scope module shows
one sentence explaining whether it follows the selected thread or the whole
Palace; it does not render a disabled or decorative switch. The Palace queue's
unused scope declarations are removed. Implementation labels and redundant
headers that do not change an owner decision are removed from the visible
surfaces while accessible names and authoritative state remain intact.

The gear glyph, popout composition, compact-phone title/navigation treatment,
and exact surviving labels are **PROVISIONAL-TASTE** for the next owner pass.
The single host authority, manifest-gated controls, real action binding, and
absence of dead controls are not provisional.

**Motivation.** The Stage had accumulated permanent controls and labels for
rare configuration, internal boundaries, and scope behavior. That chrome made
the owner scan system vocabulary before reaching the work, and one queue scope
switch did nothing at all. Moving rare app choices behind one obvious door and
deriving module controls from declared capabilities makes the interface quieter
without hiding a choice that actually changes state.

**Rejected alternatives.** A settings protocol inside every iframe would
duplicate ADR-023's host authority. Keeping internal scope switches beside the
shared gear would create two controllers for one value. Giving every module a
scope action would invent behavior the underlying queries do not support.
Disabled controls and geometry readouts would preserve visible chrome without
giving the owner a decision. A broader copy rewrite, settings search, plugin
preferences schema, or cloud-synced preferences are not needed for this packet.

## 067 — One data-bearing rendered canon inherits every gate-day finding [P4, M2ST4]

**Decision.** One foreground runner starts one fixture-isolated, populated Rack
and executes the existing M2UX1, M2ST1, M2ST2, and M2ST3 browser proofs in
sequence. The sweep measures iframe descendants at their rendered scale, clips
nodes to visible overflow ancestors, and treats same-surface SVG/canvas text
overlap as a failure alongside interactive collisions and clipped DOM text.
Occluded Stage controls are inert while a full-screen module owns the work
surface. The Stage shell assigns its header, toolbar, status, and viewport to
explicit grid rows so an empty status cannot collapse the viewport.

The fixture carries deliberately crowded Graph data, over-precise accounting,
and live control state. Its Thread End response is isolated at the fixture seam
because archive verification must not manufacture or mutate owner transcript
history. Evidence lives in a temporary directory. The same command runs after
a clean Harness and pinned Spine install in CI; the owner gate and M2XF scout
remain real-app, real-provider passes.

**Motivation.** Four useful rendered proofs were individually runnable but not
one standing release barrier. Worse, the old collision collector compared
unscaled iframe coordinates and invisible overflow content, so it could both
invent collisions and miss visual-text failures. A single command makes today's
eyes durable while keeping deterministic regression evidence separate from
owner truth.

**Rejected alternatives.** Four new duplicate suites would drift from the
proofs they claim to preserve. Static empty screenshots would miss the dense
states that caused the findings. Weakening collision tolerances would hide both
measurement bugs and product bugs. Running the canon against the owner Palace
would spend, mutate history, and violate fixture isolation. A second formatter,
label engine, or Stage model is outside this packet.
