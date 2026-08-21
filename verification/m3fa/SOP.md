# M3FA real-owner Recipe verification

Date: 2026-08-21

I started the ordinary packaged owner app from this checkout, with a disposable
Nocturne home and no scenario/fixture application:

```sh
NOCTURNE_HOME=/tmp/n8-m3fa-owner-home \
UV_CACHE_DIR=/tmp/n8-m3fa-browser-uv \
PYTHONPATH=src \
uv run --locked uvicorn harness.packaged:create_app --factory \
  --host 127.0.0.1 --port 8891
```

In the rendered Rack I opened a new channel, sent `Take this to a Symphony.`, and
filled the in-chat deliberation rather than injecting an API fixture. I signed a
three-step recipe whose first step was explicitly a search step, retained the fixed
motivation/implementation/performance judge charters, signed the displayed T2 wall,
and selected the hold-for-steering option so the current plan remained live.

I added Recipe from the Stage Library. The module loaded the same signed Symphony
identity shown on the Deck (`01M0JZZ3VAHCH0E13A5DQYWQQJ`) and rendered three inputs,
the sequential join stages, and the served milestone. The first search/current cells
were vivid; future inputs and stages stayed quiet. Selecting the current cell exposed
its running state, exact owner motivation, done-when evidence, and step identity.

I also read the running app's public endpoint directly:

```text
GET /v1/rack/query?resource=recipe_graph&as_of=now -> 200
status=live; revision=1; packet_id=01M0JZZ3VAHCH0E13A5DQYWQQJ
step-1=search/running; step-2=packet/blocked; step-3=packet/blocked
step-1 judged_by motivation, implementation, performance
step-1 blocks step-2; step-2 blocks step-3
```

## Unscripted exploration

After the first render I moved Recipe from the crowded Work layer to the existing
Graph layer, where it continued to show the same live identity beside Memory Graph.
I then created an otherwise-empty layer, added Recipe again through the Library,
selected its current step, zoomed and panned the ordinary Stage controls, and captured
the focused view. I then ran a second verification-only three-step Symphony through
the same in-chat deliberation without hold-for-steering. Re-adding Recipe on the empty
layer read that completed stack from the public endpoint: all six step/judge nodes
were passed, the grid receded, and the full-height milestone said the whole plan was
complete. Data survived the layer changes; no fixture curtain appeared and no request
returned the released-path 503.

## Evidence

- `recipe-live-focused.jpg` — real packaged app, Recipe alone on an owner-created
  layer, current search selected; graph-derived grid, joins, dimming, and milestone.
- `recipe-live-completed.jpg` — a second real signed Symphony on the same focused
  layer; all step and judge nodes passed, six complete, zero ready, and the served
  milestone visible. This capture was repeated from the exact pushed `c9b373f`
  source and its committed web bundle.
