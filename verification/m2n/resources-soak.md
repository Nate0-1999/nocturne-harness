# M2N resource watch and soak evidence

Date: 2026-08-04

This is deterministic builder evidence for Garden A-044. The browser target was
`verification.m2c.scenario_app:create_scenario_app`, which visibly labels itself
`M2C REGRESSION FIXTURE` and `DETERMINISTIC EVIDENCE - NOT THE OWNER APP`.

## Visible behavior

- At 1440 x 900, expanded Palace Vitals showed free disk, database, daemon RSS,
  daemon uptime, journal, and backup measurements in the passive gauge row.
- At 390 x 844, collapsed Palace Vitals summarized owner-local storage as
  `Resources - 100.0 GiB free - DB 7.5 MiB` without an alert, modal, or prompt.
- The browser fixture was stopped and its in-app browser tabs were finalized.

Screenshots:

- `resources-desktop-1440x900.png`
- `resources-mobile-390x844.png`

## Repeated-query bound

Command:

```sh
uv run --locked python verification/m2n/resource_soak.py
```

The real daemon HTTP Rack query path received 500 warm-up queries followed by
10,000 sequential Vitals queries. RSS was sampled every 250 queries.

```text
baseline_rss_bytes:     151371776
peak_rss_growth_bytes:    1916928
final_rss_growth_bytes:   1916928
maximum_growth_bytes:    33554432
```

Result: PASS. Peak and final growth were both 1.83 MiB, below the 32 MiB A-044
ceiling.
