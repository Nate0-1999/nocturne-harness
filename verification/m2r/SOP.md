# M2R owner SOP

## See context pressure

1. Complete one model response in a thread.
2. Read **Context Bars** beside **Palace Vitals**.
3. Treat the `used / capacity` number as the measured request total against the
   selected model's context length.
4. Treat System, History, Memory, and Tools as an estimated breakdown; their
   token counts always add back to the measured total.
5. Use **Current** for the selected thread or **Global** for all observed
   threads. A thread with no completed response truthfully says it is waiting.

The 80% mark is a reference line only. Compaction is not active and the module
does not block or alter a run.

## Reproduce the isolated proof

From `harness/`:

```sh
npm --prefix web run build
PYTHONPATH=src:. .venv/bin/python -m verification.run_fixture \
  verification.m2r.scenario_app:create_scenario_app --port 8774
```

Open `http://127.0.0.1:8774/`. The fixture redirects to its verified identity;
port 8765 remains refused by the shared fixture boundary.
