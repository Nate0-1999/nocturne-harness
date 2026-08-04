# M2O verification

`browser_check.mjs` owns a fixture process launched through the shared
port-refusing launcher, uses an explicit temporary Chromium profile, and
removes both in `finally`. It proves the server-verified full-viewport banner,
pending-accounting line, and exact-title catalog cleanup at desktop and phone
geometry.

Run from the Harness repository after building `web`:

```sh
node verification/m2o/browser_check.mjs
```

The Python regressions cover product-port refusal, durable mode-0600 receipt
spooling, stable-ID replay, degraded memory fallback, and a completed answer
when the ledger is dead.
