# M2J model device walkthrough

1. Build the committed web bundle and start `scenario_app.py` on isolated port
   8776 with a temporary `NOCTURNE_HOME`.
2. Open `/?fixture=M2J%20REGRESSION` and confirm the full-surface fixture banner.
3. Click the active model in Chat. Confirm MODEL DEVICE opens as a control
   plugin, reports the resolved route, and exposes exactly the six manifest
   bindings.
4. Move Temperature one step and choose High reasoning effort. Confirm each
   value becomes explicit, History advances, and the fixture trace contains a
   `parameter.change` for each real descriptor.
5. Resolve `openrouter:fixture/next`. Confirm both MODEL DEVICE and Chat's
   active-model header turn together, the trace contains `parameter.change`
   plus `model.change`, and the named resolver saw the request.
6. Scrub History to the beginning. Confirm the device replays the original
   route and provider-inherited values, and controls become read-only while
   viewing the past.
7. Switch to Defaults. Confirm it is a read-only registry/default view and the
   saved scope toggle never becomes a parameter write.
8. Attempt an unbound write as module `chat`. Confirm HTTP 403, no value change,
   and a durable `parameter.refused` event with reason `unbound`.
9. Repeat at 390×844. Every binding, value, selector, scope control, and history
   control must remain readable without horizontal overflow.

The fixture is deterministic evidence, never the owner app and never evidence
of a live broker call. Unit tests separately trace all five request parameters
into the fresh Pydantic/OpenRouter settings body.
