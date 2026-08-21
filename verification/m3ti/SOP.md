# M3TI real-browser proof

This is a deterministic, visibly curtained regression fixture. It proves the
real Rack and Memory Gate presentation; the Spine scorer suite proves the
ranking math independently.

1. Start the fixture with an isolated state root:

   ```console
   NOCTURNE_HOME=/tmp/n8-m3ti-browser-home \
   UV_CACHE_DIR=/tmp/n8-m3ti-browser \
   PYTHONPATH=src uv run --locked uvicorn \
     verification.m3ti.scenario_app:create_scenario_app \
     --factory --host 127.0.0.1 --port 8771
   ```

2. Open `http://127.0.0.1:8771/` in a real browser and send
   `Show the thread-local memory ranking.`
3. At the first-turn Memory Gate, verify:
   - the yellow fixture curtain is visible;
   - `Born in this thread` is rank 1 at 0.641;
   - its provenance reads `Project 1.000`, `Thread 1.000`, `Location —`;
   - `Threadless legacy twin` is rank 2 at 0.610;
   - its Thread provenance is `—`, not a guessed midpoint.

Do not use this fixture as owner-app, provider, or production-Palace evidence.
