---
name: nocturne-plugin-contributor
description: Author and verify Nocturne rack visualizers and parameter controls, using the public message bridge, live data catalog, and shared Stage layout.
---

# Nocturne rack plugins

Nocturne is a conversation workspace with a memory service called Spine (the Palace). Its Stage arranges independent instruments. A visualizer reads; a control changes a declared parameter. Both use the same rack connection as the shipped Spend and Model device modules.

Start with the user's desired observation or control. Read [the data catalog](references/data-catalog.md) for the matching query, event and descriptor. Use the existing interface before adding a new endpoint. The repository root is two directories above this skill.

## What ships today

The Library imports a JSON bundle by file or paste. Keep your source as a folder with a manifest and `index.html`; package the HTML into the bundle's `html` field. Folder drop and automatic hot reload are design goals, not implemented import options. Reimporting the same ID updates a bundle. Import and Stage placement persist in the browser for this Nocturne origin.

```json
{
  "id": "plugin:burn-gauge",
  "name": "Burn gauge",
  "html": "<!doctype html><h1>Burn gauge</h1>",
  "streams": ["run.usage", "run.done"],
  "actions": [],
  "bindings": []
}
```

IDs use `plugin:` followed by lowercase letters, digits or hyphens. Names and HTML are nonempty strings. Streams are exact C.7 names or prefix wildcards such as `run.*`. Imported panels use API version `1.0.0`, GLOBAL scope by default, preferred 24×20 grid units, and the shared Stage bounds, movement and resize handles. Scope can be changed in module settings. The import adapter creates a visualizer for an empty action list, otherwise a control. Its permitted actions are `parameter.write`, `rack.scope.get` and `rack.scope.set`; parameter writes must name a declared binding.

The authoring source of truth is [rackPlugins.ts](../../web/src/rackPlugins.ts), [rack.tsx](../../web/src/rack.tsx), and [rackBridge.tsx](../../web/src/rackBridge.tsx). The latter defines both sides of the same versioned connection used by shipped modules. This bundle adapter does not replace every built-in module or implement face/theme packaging.

## Three surfaces, one connection

Plugins receive events, queries and selection. There is no notification surface: Nocturne's attention contract reserves demands for judge-released Deck returns. Sandboxing keeps plugins away from credentials and the host DOM. Imported HTML has no network egress; embed assets and code in the bundle. Controls bind descriptors so value validation, history and authority remain in the registry.

Use this connection in `index.html`; all displayed values are illustrative until a live reply arrives:

```html
<output id="value">Connecting…</output>
<script>
let port, snapshot, sequence = 0;
const pending = new Map();
function request(message) {
  const request_id = String(++sequence);
  return new Promise((resolve, reject) => {
    pending.set(request_id, {resolve, reject});
    port.postMessage({...message, request_id});
  });
}
addEventListener('message', event => {
  if (event.source !== parent || event.data.type !== 'nocturne.rack.connect') return;
  port = event.ports[0];
  if (!port) return;
  snapshot = event.data.snapshot;
  port.onmessage = ({data}) => {
    if (data.type === 'snapshot') snapshot = data.snapshot;
    if (data.type === 'response' || data.type === 'error') {
      const callback = pending.get(data.request_id);
      if (callback) {
        pending.delete(data.request_id);
        data.type === 'error' ? callback.reject(new Error(data.error)) : callback.resolve(data.result);
      }
    }
    // data.type may also be envelope, selection or resize; see the catalog.
  };
  port.start();
  document.getElementById('value').textContent = 'Connected';
});
parent.postMessage({type:'nocturne.rack.ready', module_id:'plugin:burn-gauge'}, '*');
</script>
```

Use your bundle ID in the ready message. The host answers with a transferred MessagePort, manifest, snapshot, selection, theme ID and optional pressed colorway. For imported HTML, apply your styles explicitly; it does not execute the first-party React theme injector. Do not assume host CSS inheritance across an iframe. Respond to the supplied theme/colorway if the plugin offers multiple palettes.

## Visualizer walkthrough: Spend

Use `actions: []`. After connection, call `request({type:'query', request:{resource:'vitals', as_of:'now'}})`. Render the actual returned spend fields from the catalog. Refresh on subscribed `run.usage` / `run.done` events, or a user refresh control; never synthesize a zero when a value is absent. `spend_table` provides the conversation/model breakdown. The shipped [VitalsModule.tsx](../../web/src/VitalsModule.tsx) is the complete reference, including missing prices and refresh failure. It consumes the same query surface as imported HTML.

Package your folder with ordinary JSON serialization, for example `json.dumps({**manifest, "html": Path("index.html").read_text()})`; don't concatenate unescaped HTML into JSON. In Nocturne, open Library, choose the JSON file or paste it, then Import plugin. Verify a live value, resize the panel, and reload to verify placement.

## Control walkthrough: Temperature

Declare `actions: ["parameter.write"]` and `bindings: ["model.temperature"]`. Query `parameters` using `snapshot.selectedThreadId`; build the input from the returned descriptor's range, step and current value. Disable application while no thread is selected or a historical position is displayed. On the user's change:

```js
await request({type:'dispatch', action:{
  type:'parameter.write', thread_id:snapshot.selectedThreadId,
  parameter_id:'model.temperature', value:0.5
}});
const updated = await request({type:'query', request:{
  resource:'parameters', thread_id:snapshot.selectedThreadId, as_of:'now'
}});
```

Show the returned value and change history, not just an optimistic knob position. Null resets optional parameters to their provider default. The host rejects unbound writes, and the daemon validates the descriptor and refuses changes during an active run. Scorer changes use a separate versioned simulation/activation contract; a model-parameter plugin cannot bypass it. [ModelDevice.tsx](../../web/src/ModelDevice.tsx) is the full control reference, including model, effort, ranges and history scrubbing.

## Modification guide and contribution check

- Recommended: new visualizers, descriptor controls, palettes and layouts. Start with existing data; these have the smallest authority footprint.
- Modify with care: scene faces and Deck arrangement. Preserve selection, ordering and accessible navigation.
- Law-bound: gates, approval queues and boundary cards. Their complete cards, removal reasons, add-backs and disposition events are the consent and learning record. Local source changes are the user's choice; contributions must preserve those contracts.

For a contribution, run web unit tests, lint, build and the rendered canon (`python scripts/run_ui_canon.py --help` gives current options). Add a meaningful test only for new mechanics. Walk the changed feature with real permitted data, record missing-data/refusal states, and capture the required B.6 screenshots across affected palettes and sizes. Re-prove impacted ledger rows through Garden when operating a Garden packet. Keep fixture principals explicit; this skill grants no access to an owner's home or Palace and no release permission. Report implementation limits honestly, including unsupported query history or packaging modes.
