# M3BW browser-hands evidence

This directory is a verification identity, not an owner Rack capture. The real
product turn used the pinned OpenRouter route and the production Harness agent,
tool capability, run loop, and append-only transcript journal. The journal itself
stayed in a private temporary directory because owner transcripts do not belong in
Git.

The agent navigated to `tiny-page.html`, read it, filled `#owner-note`, clicked
`#reveal`, and returned `browser-hands.png` through pydantic-ai as native
`image/png` input. The real model then described the visible title, filled note,
button, and revealed signal correctly. `trace-summary.json` records the bounded
provider and journal facts; `golden-transcript.json` freezes the expected action
order, visible facts, and fence behavior without copying private transcript data.

Reproduce the headless screenshot after installing the locked environment and
Chromium:

```sh
uv run --locked playwright install --only-shell chromium
PYTHONPATH=src uv run --locked python verification/m3bw/capture.py
```
