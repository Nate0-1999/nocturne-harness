# PI dependency receipt and update ritual

Nocturne consumes `@earendil-works/pi-coding-agent` as one intact published
toolset. It does not copy, fork, or edit PI source. `package-lock.json` is the
complete npm resolution; PI's own published shrinkwrap remains inside that
package. `LICENSE.upstream` preserves the MIT notice that the npm tarball does
not carry as a standalone file.

## Why this upstream and publisher are canonical

Checked 2026-08-17 from primary GitHub and npm surfaces:

- `https://github.com/badlogic/pi-mono` returns a permanent redirect to
  `https://github.com/earendil-works/pi`.
- Both Git URLs resolve the same current HEAD and the same `v0.84.2` tag.
- The `v0.84.2` tag is commit
  `914cf1472e715297caa30db4b9535d534a9eb718`; npm's `gitHead` for package
  `0.84.2` is that exact commit.
- The npm package names the Earendil repository and its publisher set retains
  PI creator `badlogic` alongside `mitsuhiko` and `rwachtler`.
- The exact registry artifact, integrity, source, license, engine, and
  publisher identities are frozen in `dependency.json`.

That continuity resolves the custody wrinkle. A source vendor would add a
second update surface without adding provenance, so dependency-first wins.

## Boundary

`harness.toolset` is Nocturne's interface. Only
`harness.pi_toolset_adapter` speaks PI's strict LF-delimited JSON RPC. The
adapter launches the dependency with ephemeral sessions, project resources
disabled, and startup network work disabled. No runtime path installs or
updates packages; a missing dependency is a plain refusal with this ritual as
the remedy. M3E adds movement-enforced file operations through the owned seam.

## Mechanical update

From the Harness checkout:

```bash
UV_CACHE_DIR=/tmp/nocturne-pi-update-uv \
  uv run --locked python scripts/update_pi_toolset.py 0.84.2
```

The updater refuses a changed npm publisher set, a non-MIT package, a
noncanonical repository, or a tag/npm `gitHead` mismatch. It then regenerates
the exact package manifest, dependency receipt, upstream notice, and lockfile;
installs with lifecycle scripts disabled; runs a real offline RPC smoke; and
runs the focused seam and unchanged golden suites.

Review the dependency diff and upstream changelog, then finish with ordinary
ground:

```bash
UV_CACHE_DIR=/tmp/nocturne-pi-harness-uv PYTHONPATH=src \
  uv run --locked pytest -q -m 'not contract'
UV_CACHE_DIR=/tmp/nocturne-pi-spine-uv \
  TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock \
  TESTCONTAINERS_RYUK_DISABLED=true PYTHONPATH=src \
  uv run --locked pytest -q
```

Rollback is the reverse mechanical change: restore the prior manifest,
receipt, notice, and lockfile from Git; run `npm ci --ignore-scripts`; rerun
the same smoke, goldens, and ordinary suites. No database, owner record, or
provider state participates.

The initial no-op proof used this updater against the already-pinned `0.84.2`:
all four managed metadata files remained byte-identical, the real RPC smoke
passed, and the focused goldens stayed unchanged and green.
