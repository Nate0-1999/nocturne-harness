# M2P experiential verification

1. Build `web` and launch `PYTHONPATH=src:. uv run --locked python -m verification.run_fixture verification.m2p.scenario_app:create_scenario_app --port 8786`.
2. Open `http://127.0.0.1:8786/?fixture=M2P%20REGRESSION` at 1440×900 and open Injection.
3. Verify GLOBAL shows the Palace-wide controls and explicitly says it has no fabricated gate preview.
4. Switch CURRENT, change Minimum match, and verify candidate score/rank/disposition previews change while FORCE remains disabled.
5. Run DEEP. Verify the held-out score, signed delta, digest prefix, and two-dimensional accuracy slice; verify FORCE is now enabled.
6. Change any knob and verify the receipt disappears and FORCE disables. Run DEEP again, FORCE the exact recipe, and verify the active version changes.
7. Audition the learner proposal and verify `would add`/`would drop` presentation marks without changing the incumbent; then inspect `/__scenario__/trace` for separate simulation, force, and audition records.
8. Repeat the DEEP view at 390×844 and verify no horizontal overflow.

This deterministic fixture is product verification, not the real OpenRouter owner app.
