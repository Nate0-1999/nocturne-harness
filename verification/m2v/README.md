# M2V verification — editable web assets and readiness voice

Session: `codex / 2026-08-06 / 7b4e`

## Cold editable-checkout acceptance

The ignored `src/harness/_web` stopgap and committed `web/dist` were both moved
aside before the check. From that state, with Node.js available, the real
`harness.packaged:create_app` factory invoked the existing canonical web build
and served `/` through a FastAPI `TestClient`:

```text
vite: 287 modules transformed
status=200 content_type=text/html; charset=utf-8
```

The generated `web/dist` was byte-for-byte identical to the committed build.
The original checkout directories were then restored; no generated package
copy was retained.

## Refusal and regression evidence

- `tests/test_packaging.py` covers wheel preference, editable `web/dist`
  fallback, cold Node.js build, and the one-line no-Node remedy.
- `tests/test_onboarding.py::test_readiness_stops_on_the_first_plain_web_refusal`
  proves the readiness loop reads one 503 body and stops before sleeping or
  polling again.
- `tests/test_daemon.py::test_missing_web_build_is_explicit` proves the served
  refusal states both the situation and the next action.
- `scripts/check_test_motivations.py`: `376 tests, 0 grandfathered`.

## Final gates

```text
Spine:   222 passed
Harness: 658 passed, 3 deselected
Web:     ESLint PASS; 7 unit tests PASS; TypeScript + Vite build PASS
Ruff:    PASS
```
