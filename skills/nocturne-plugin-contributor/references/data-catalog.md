# Rack data catalog

These compact sample fragments explain fields, not verification results. Use live responses and the linked types when implementing a view. IDs shown as `…` stand for actual server-issued IDs; don't send the sample fragments back as requests.

## Query surface

Send `{type:"query", request_id:"1", request:{resource:"catalog", as_of:"now"}}` through the MessagePort. Replies are `{type:"response", request_id:"1", result:{status:"live", as_of:null, data:…}}`, or `{type:"error", request_id:"1", error:"…"}`. `historical_unavailable` has `data:null`; it is not an empty historical result.

| Resource | Contents and representative fragment |
|---|---|
| `catalog` | Thread list: `[{"thread_id":"…","title":"Compass","updated_at":"2026-09-15T00:00:00Z","message_count":2,"archived":false}]`. Workspace/project/location and unresolved proposal fields may also be present. |
| `selected_thread` | Selected thread state or null: `{"messages":[],"resolvedModel":"openrouter:openai/gpt-4.1-mini","memoryPanel":{…}}`. The ID is in `snapshot.selectedThreadId`; use exported `ThreadState` in `web/src/store.ts` for the full structure. |
| `memory_panel` | Selected thread's panel or null: `{"status":"ready","total":1,"items":[{"memory":{"memory_id":"…","label":"Compass","body":"Brass","revision":1,"pin":false},"score":0.89,"in_context":true,"thread_excluded":false}]}`. Revisions and complete provenance belong to each item. |
| `vitals` | Measured usage/spend, accounting, resources and learning. Representative fields: `{"window_minutes":60,"resources":{"database_bytes":9751759},"learning":{…}}`. Start with `VitalsModule.tsx` and `vitals_fixture.py`; do not equate ledger spend with provider billing. |
| `spend_table` | `{"as_of":"…","window_minutes":60,"threads":[{"thread_id":"…","input_tokens":"1204","output_tokens":"34","total_usd":"0.000537","total_unpriced_lines":0,"models":[]}],"purposes":[]}`. Decimal strings preserve exact quantities; null cost means unpriced. Full metrics are in `spine_client.py`. |
| `context_window` | `{"scope":"CURRENT","selected_thread_id":"…","observations":[],"aggregate":null}`. Selected thread context budget/used categories; request with `thread_id`. See `ContextWindowSnapshot` in `src/harness/context_window.py` and `ContextBars.tsx`. |
| `parameters` | `{"thread_id":"…","as_of":"…","resolved_model":"openrouter:openai/gpt-4.1-mini","descriptors":[…],"values":{"model.temperature":0.5},"changes":[…]}`. Requires `thread_id`; supports timestamp history in the daemon's recorded parameter history. |
| `memory_graph` | `{"as_of":"…","graph_edge_sim":0.75,"nodes":[{"memory":{…},"revisions":[]}],"edges":[],"omitted_memory_ids":[]}`. An optional thread scope restricts memory membership. |
| `scorer_console` | `{"scope":"GLOBAL","thread_id":null,"active_version":"…","descriptors":[],"configurations":[],"activations":[],"proposed_versions":[],"accuracy":[],"learning":{},"candidates":[]}`. See `InjectionConsole.tsx` and `ScorerConsoleSnapshot` in `spine_client.py`; this read does not activate a proposal. |
| `recipe_graph` | `{"schema_version":1,"nodes":[{"node_id":"step-1","label":"Build","kind":"packet","state":"ready"}],"edges":[]}` (fragment). See `RecipeGraphSnapshot` in `src/harness/recipe_graph.py` for snapshot metadata. Absence is not completed work. |

Apart from `parameters`, current query adapters return `historical_unavailable` for past timestamps. `thread_id` / `thread_ids` are optional scope fields where supported. Attuned rack context supplies the matching thread selection. SQL views are service internals, not direct plugin connections: Spine's spend pipeline materializes `v_spend_rate`, `v_thread_cost`, `v_run_cost`, `v_memory_cost` and `v_cache_efficiency`; use `vitals` / `spend_table` to obtain their public projections.

## Events, snapshots and selection

The initial connection contains `snapshot` with `catalog`, `selectedThreadId`, `currentProjectKey`, `projectPaths`, `threads`, `drafts`, `connection`, `globalError` and `attunement`. Later snapshots arrive as `{type:"snapshot", snapshot:{…}}`.

Declared streams match exact names or suffix wildcards. A delivered event is `{type:"envelope",event:{direction:"inbound",envelope:{type:"run.delta",thread_id:"…",machine_id:"…",agent_id:"…",payload:{run_id:"…",kind:"text",text:"Hello"},…}}}`. Full envelopes and payload unions are exported by `web/src/protocol.ts` and validated in `src/harness/envelope.py`. Event IDs and run IDs are ULIDs; memory/thread/injection IDs are UUIDs where the corresponding type says so.

| Stream | Payload role / representative fields |
|---|---|
| `thread.create` | A new thread and its requested workspace. |
| `thread.snapshot` | Restored messages, open gate, active run, project/workspace and request correlation. |
| `prompt.submit` | `{"prompt":"Hello"}` plus optional image/launch/proposal fields. |
| `prompt.queued` | Acknowledges an accepted queued prompt; don't treat it as a completed run. |
| `gate.open` | Injection ID, proposed cards and near misses; the model is waiting. |
| `gate.commit` | Human dispositions for that injection, including additions/removals. |
| `gate.dismiss` | Closes the corresponding gate. |
| `run.started` | `{"run_id":"…","resolved_model":"openrouter:…"}` and run context. |
| `run.delta` | Text/thinking: `{"run_id":"…","kind":"text","text":"Hello"}`; tool/event: `{"run_id":"…","kind":"event","event":{…}}`. |
| `run.usage` | `{"run_id":"…","requests":1,"input_tokens":1204,"output_tokens":34}`; optional cache read/write token counts. Cumulative, not per-frame increments. |
| `run.cancel` | Cancellation request for a run. |
| `run.done` | `{"run_id":"…","stop_reason":"end_turn","partial":false}`; error terminals may carry `error_message` / `provider_error`. |
| `memory.panel.update` | State, conflict or error response, operation and request correlation; inspect the discriminated payload. |
| `error` | Code, readable message and optional phase/run correlation. |

Other nonblank event types are valid extensions. `run.steer`, `plan.update`, `checkpoint.created`, `checkpoint.restore` and `presence.update` are reserved names; declaration alone does not prove those features run. Retain unknown data without inventing behavior.

Resize events are `{type:"resize",event:{module_id:"plugin:burn-gauge",width:600,height:360,grid_width:12,grid_height:10}}`. Dimensions come from the host; let content reflow. Selection uses `{type:"selection",selection:{kind:"thread",id:"…"}}`. Other kinds: project, memory, module and spend_lane (with `as_of`). Optional spatial `{layer_id,frame_id}` follows the shared selection visibility rules. Null clears selection.

## Writable model descriptors

All current model descriptors have scope `thread`, authority `free-journaled`, default null. The initial resolved `model.slug` is a real model name. Descriptor samples come directly from `MODEL_PARAMETER_DESCRIPTORS` in `src/harness/parameter_registry.py`:

| ID | Type | Range/options |
|---|---|---|
| `model.slug` | model | Executable `openrouter:provider/model` string |
| `model.temperature` | number | 0–2, step .05 |
| `model.top_p` | number | 0–1, step .01 |
| `model.top_k` | integer | 0–500, step 1 |
| `model.max_tokens` | integer | 1–131072, step 1 |
| `model.effort` | option | none, minimal, low, medium, high, xhigh |

Example descriptor: `{"id":"model.temperature","label":"Temperature","type":"number","range":{"minimum":0,"maximum":2,"step":0.05},"options":[],"default":null,"scope":"thread","authority":"free-journaled"}`.

Example accepted change: `{"event_id":"…","parameter_id":"model.temperature","scope":"thread","thread_id":"…","actor":"human","timestamp":"2026-09-15T00:00:00Z","old_value":null,"new_value":0.5}`. Query the returned history rather than fabricating local receipts. Scorer descriptors are read from `scorer_console`; their versioned simulation and activation actions belong to the shipped Injection Console contract and are not exposed by the imported model-control adapter.
