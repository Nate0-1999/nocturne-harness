# D3 packaging verification

Date: 2026-08-01

This evidence was produced from the `nocturne-ai==0.1.0` and
`nocturne-spine==0.1.0` wheel artifacts built from the release worktrees. No
editable checkout was present on `sys.path` during the installed-wheel checks.

## Artifact checks

- Both distributions build as an sdist and wheel.
- Each direct wheel is byte-identical to the wheel rebuilt from its sdist.
- `twine check` passes all four artifacts without warnings.
- The Harness sdist contains 30 release entries and excludes Garden, internal
  verification, tests, Node source, `node_modules`, and local environment data.
- The installed `nocturne` entry point exposes exactly `init`, `up`, `deploy`,
  and `open`.

Artifact SHA-256 values:

| Artifact | SHA-256 |
| --- | --- |
| `nocturne_spine-0.1.0-py3-none-any.whl` | `0a83d082ccfad2f16621d3386b15ce35cdfdacfb42e6ac20edf5f3372b220587` |
| `nocturne_spine-0.1.0.tar.gz` | `08a08acb5fcf42d2ddad2624cf214402c34af15ab9283187b5df0fcf9774f6af` |
| `nocturne_ai-0.1.0-py3-none-any.whl` | `1375a7f761b2410b809f99ed3fef10e54040354c054187a7d0a295efc8f7cf91` |
| `nocturne_ai-0.1.0.tar.gz` | `99ff46627a26f0e7ef6e132ca1751bfb205310a1f12737d583dde32ed35f46dc` |

## Installed-wheel local acceptance

An isolated `NOCTURNE_HOME` was configured with mode `0700`; its environment
file was written with mode `0600`. `nocturne up --no-open` pulled the packaged
Postgres service, ran the packaged migrations, started the daemon and bundled
web app, and returned HTTP 200 for both health and UI probes.

The browser then created a new memoryless thread through the bundled UI, passed
the first-turn memory review with zero injected memories, and received the
expected model response. The screenshot contains no secret material:

![Installed-wheel chat acceptance](chat-acceptance.png)

## Cloud dry-run

The installed wheel ran `nocturne deploy --dry-run` against the fixed
`n8-memory-palace` / `us-central1` target. The first attempt caught an invalid
Artifact Registry read argument; that command was corrected, covered by a
regression test, rebuilt, reinstalled, and rerun. The final run exited normally
after printing all 20 stages and made no changes.

The complete redacted output is preserved in
[`deploy-dry-run.txt`](deploy-dry-run.txt).

The observed plan was:

- exact/no-op: active project, billing link, PostgreSQL 16 foundation, SQL
  protection, both runtime secrets, dedicated runtime identity, four scoped
  IAM grants, immutable Artifact Registry repository, and the complete armed
  D2 topology;
- blocked: the existing database/user/managed-URL-secret tuple disagrees, and
  the observed Alembic head is not forward-compatible with the packaged head;
- forward work, not executed: create the immutable Spine image, update the
  single Cloud Run service, and run remote verification.

The blocked live state is intentionally not adopted, rotated, deleted, or
replaced. Resolution requires an owner decision under the D1 boundaries; it is
not silently widened into D3 authority.

## Public-index gate

Public installation remains a separate release gate. D3 is not complete until
`pipx install nocturne-ai==0.1.0` succeeds against the public PyPI index.
