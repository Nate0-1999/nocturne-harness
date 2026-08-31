# M3CU rendered curator proof

Run the deterministic honest-display fixture, then execute:

```sh
node verification/m3cu/browser_check.mjs \
  --base-url http://127.0.0.1:8807 \
  --fixture 'M2ST3 REGRESSION' \
  --evidence-dir verification/m3cu/evidence
```

The check proves that cadence and activity live in Palace State, a curator
proposal retains its rationale in the ordinary Palace Queue, and declining it
uses an explicit human decision without changing the Palace.
