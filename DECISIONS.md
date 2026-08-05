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
