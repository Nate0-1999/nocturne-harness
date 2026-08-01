# M2A — Broker receipt seam evidence

Date: 2026-08-01
Session: `codex / 2026-08-01 / a4d2`

Harness asks OpenRouter to include native usage, captures each new Pydantic AI
`ModelResponse`, and synchronously submits one A-027 batch before terminalizing
the turn. Lines retain daemon-owned principal, machine, origin agent, thread,
run, and prompt lineage. Ordinary chat uses `purpose=building`; `/remember`
label calls use `purpose=remember` and carry the created memory id when one
exists.

`tests/test_spend.py` proves nonzero price-class splitting, reasoning
non-duplication, direct-Anthropic versus inclusive prompt accounting, exact
aggregate USD preservation, honest allocation basis, downstream-provider
selection, and ref fallback. `tests/test_agent_runtime.py` proves the receipt
write completes before the adapter returns and that failure emits a sanitized
`spend_unavailable` error rather than silently losing charged work.

The live Docker contract builds the Spine wheel, applies its packaged migration
head, starts pgvector/Postgres, and executes create/patch plus A-027 receipt
insert → equal replay → differing replay conflict through the typed
`SpineClient`.

Final local commands:

```text
.venv/bin/ruff check .
All checks passed!

PYTHONPATH=src .venv/bin/pytest -q -m 'not contract'
531 passed, 3 deselected

PYTHON=.venv/bin/python tests/contract/run.sh
3 passed
```

The live contract uncovered and repaired two pre-existing image-path defects:
the Docker builder omitted the package-declared `README.md`, and the contract
Compose file bypassed Spine's existing packaged migration entrypoint. The
builder/deploy materializer now carry the README, and Compose invokes
`python -m spine.db.migrate`.
