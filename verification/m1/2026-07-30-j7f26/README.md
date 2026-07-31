# M1 J evidence index — 2026-07-30

Session: `codex / 2026-07-30 / 7f26`

This directory is the independent J continuation after the prior judge process
stopped. The owner confirmed there was no live J worker. I recovered the stale
claim, verified inherited ground, used the stopped process's append-only J1/J2
artifacts where they were sound, and generated fresh J3–J8 evidence. I did not
change product implementation.

## Result

Overall verdict: **FAIL**.

J0 and J3–J8 pass. J1 and J2 fail on named trace/action coupling that the
available artifacts do not prove. The failures are evidence/protocol failures;
this run did not establish a product defect.

The normative verdict is [`../VERDICT.md`](../VERDICT.md).

## Evidence map

| Item | Result | Primary evidence |
|---|---|---|
| J0 | PASS | [`j0-scope-journal-audit.md`](j0-scope-journal-audit.md) |
| J1 | FAIL | stopped-agent images `../2026-07-30-j4d73/01`–`04`; [`j1-j2-residue-audit.md`](j1-j2-residue-audit.md) |
| J2 | FAIL | stopped-agent images `../2026-07-30-j4d73/05`–`07` and three wire traces; [`j1-j2-residue-audit.md`](j1-j2-residue-audit.md) |
| J3 | PASS | images `08`–`12`; [`j3-h5-trace.jsonl`](j3-h5-trace.jsonl) |
| J4 | PASS | images `20`–`23`; [`j4-quarantine-trace.jsonl`](j4-quarantine-trace.jsonl) |
| J5 | PASS | images `24`–`36`; H6 desktop/mobile and H8 traces |
| J6 | PASS | [`j6-replay.md`](j6-replay.md) |
| J7 | PASS | images `16`–`19`; [`j7-memory-death-trace.jsonl`](j7-memory-death-trace.jsonl) |
| J8 | PASS | images `13`–`15`; [`j8-h5-mobile-trace.jsonl`](j8-h5-mobile-trace.jsonl) |

The H4 queue/reload/cancel rewalk is recorded in images `39`–`41` and
[`h4-mobile-trace.jsonl`](h4-mobile-trace.jsonl). The H8 Markdown/sanitization
rewalk is recorded in images `37`–`38` and
[`j5-h8-trace.jsonl`](j5-h8-trace.jsonl).

## Controlled environment

- Fresh stopped-agent clones were initially clean at Harness `d87a6f4` and
  Spine `5c9ac72`.
- The isolated Compose services were
  `nocturne-j-4d73-spine-1` and `nocturne-j-4d73-postgres-1`.
- Hosted exchanges retained from the stopped agent contained only synthetic
  prompts. New J3–J8 calls used deterministic local `FunctionModel` fixtures;
  hosted-model credentials were explicitly unset.
- Mandatory ground verification passed before judgment:
  - Harness: `356 passed, 2 deselected`
  - Spine: `160 passed`
- Focused trace assertions:
  - H5 desktop: PASS, 11 records
  - H5 mobile: PASS
  - H6 desktop: PASS, 58 records
  - H6 mobile: PASS, 62 records
  - H8 mobile: PASS, 18 records
  - J6 focused replay: PASS, 1 test

## Hygiene

All fixture cleanup used exact UUIDs and CAS/API paths. A final read-only query
found zero ACTIVE rows across the J principals matching
`h5-verification-*`, `h6-verification-*`, `h8-verification-*`, and
`nocturne-j-4d73`. The browser viewport override was reset.
