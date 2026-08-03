# M2M rendered reconciliation proof

1. Build `web` and launch the visibly bannered deterministic fixture on isolated port 8779:
   `PYTHONPATH=src:. uv run --locked uvicorn verification.m2m.scenario_app:create_scenario_app --factory --host 127.0.0.1 --port 8779`.
2. Open `http://127.0.0.1:8779/?fixture=M2M%20REGRESSION` at 1440 x 900.
3. Confirm the production rack renders `Ledger drift · +$0.050000000000` as one compact danger-colored line, with the fixture banner visible and no popup, notification, or additional card.
4. Collapse Vitals and confirm the same Palace-wide drift remains watchable without covering Chat.

This fixture exercises the built production SPA and daemon boundary. It is deterministic UI evidence, not the owner app and not evidence of a live OpenRouter call.
