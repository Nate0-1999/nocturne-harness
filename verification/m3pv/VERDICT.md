# M3PV — tool-layer verification

## Owner answer

**Finish M3PV, but hold the swap.**

The official Pydantic AI Harness is a credible replacement base. Its released
filesystem and shell capabilities can sit behind NOCTURNE's one owned adapter,
and the disposable prototype proves that the location fence can refuse before
the act, survive symlinks, preserve free reads, and refresh location state
before the next act.

It is not an exact replacement today. Version 0.24.0 requires
`pydantic-ai-slim>=2.28.0` while NOCTURNE pins Pydantic AI 2.12.0. Its file
search cannot return context lines, and its Skills capability loads a
`SKILL.md` body but does not expose the skill's bundled scripts, references, or
assets. Calling the proposed change a tool-only rearrangement would therefore
hide a framework upgrade and owner-visible behavior loss.

This is a **HOLD**, not a rejection of the upstream library. Do not flesh or
claim the swap packet until the owner gives the final go and the three stop
conditions below are met.

## Verdict table

`PASS` means the released capability plus a narrow owned adapter covers the
required behavior. `PARTIAL` means the useful core exists but exact behavior
still differs. `GAP` means the candidate would lose a charged capability.

| Surface | Verdict | What the released candidate proves | What remains |
|---|---|---|---|
| `read(path, offset=1, limit=2000)` | PASS | Text reads, bounded lines, 1-index-to-0-index adaptation, free reads beyond the current location, credential refusal | Output text changes; binary reads produce a notice rather than content. Current PI image content is already reduced to a notice by the RPC bridge, so this is not the stop condition. |
| `edit(path, edits[])` | PASS | Exact replacement, uniqueness checks, optimistic hash protection | Candidate edits one replacement at a time. The prototype preserves NOCTURNE's atomic multi-edit contract by validating every original-file span, composing once, then issuing one hash-guarded upstream edit. |
| `write(path, content)` | PASS | Create, overwrite, parent creation | Keep NOCTURNE's canonical-path preflight outside the commodity capability. |
| `grep(...)` | GAP | Regex, literal/case adaptation, glob, result limit | No context-line behavior. Rebuilding grep in our adapter would defeat the reason to adopt a commodity tool. Exact output also changes. |
| `find(pattern, path, limit)` | PASS | Recursive glob find and result limit | Exact output changes; pin it before a swap. |
| `ls(path, limit)` | PASS | Bounded directory listing | Exact output changes; pin it before a swap. |
| `bash(command, timeout=None)` | PARTIAL | One-shot command execution; a macOS `sandbox-exec` wrapper still gives the hard current-location write fence | Upstream allow/deny filters are documented as best effort, so they are not the security boundary. Its positive default timeout and output cap differ from today's optional-timeout contract. Keep the owned OS sandbox and withhold background-process tools. |
| Location fence and `move` | PASS | Prototype blocks outside writes and symlink escapes before execution; movement emits and refreshes synchronously before the next act | Location/presence remains NOCTURNE authority, not an upstream concern. |
| Skills | GAP | Progressive metadata first and deferred `SKILL.md` instructions | No model-visible path to bundled scripts, references, or assets; behavioral frontmatter is ignored. This misses the common-core requirement. |
| Guardrails | PASS | Validated tool arguments can be inspected before execution and blocked, replaced, retried, or approved | Argument inspection cannot secure shell redirects or scripts. The OS sandbox stays. |
| Subagents | PASS | Independent history, delegated tasks, budgets, shared usage, and optional capability inheritance exist | This is capability coverage only. It does not replace Symphony authority, staging, review, or judgment. Do not adopt it in the tool swap. |
| Compaction | PASS | Sliding windows, tool-result clearing, file-read dedupe, summaries, manual compaction, and receipts exist | NOCTURNE keeps journal, memory, receipt, and Context Bar authority. Do not adopt it in the tool swap. |
| Dependency compatibility | GAP | Package supports Python 3.10+ and is MIT licensed | 0.24.0 raises the Pydantic AI floor from NOCTURNE's 2.12.0 pin to at least 2.28.0. That needs its own compatibility evidence. |

## Disposable proof

The prototype and executable slice live beside this verdict:

- `fenced_wrapper_prototype.py` is verification evidence, not a production
  adapter. It uses only public `FileSystemToolset` and `ShellToolset` APIs.
- `test_candidate_tool_slice.py` exercises all six file tools, atomic
  multi-edit refusal, free reads, write and symlink fences, move-refresh order,
  one-shot OS-fenced shell, remote-state refusal, the grep gap, binary-read
  behavior, and the Skills resource gap.
- The environment was disposable:
  `/tmp/nocturne-m3pv.OkV5dY/venv`.

Released artifact inspected:

- `pydantic-ai-harness[skills]==0.24.0`
- wheel: `pydantic_ai_harness-0.24.0-py3-none-any.whl`
- wheel size: `734392` bytes
- wheel SHA-256:
  `f1b738b788b48a30570d47ea094b0e6cbcb4ff1b3ec5a889d0d37691733178a1`
- installed candidate package: `2.9M`; complete disposable environment: `40M`
- current vendored PI runtime: `142292 KiB`, with
  `@earendil-works/pi-coding-agent==0.84.2`
- package metadata: Python `>=3.10`, MIT,
  `pydantic-ai-slim>=2.28.0`

Sources: [official repository](https://github.com/pydantic/pydantic-ai-harness),
[PyPI release](https://pypi.org/project/pydantic-ai-harness/). The project is
still on a fast-moving 0.x API surface; pin the exact release and wheel digest
in any authorized swap.

## Runs

Candidate slice, inside the disposable environment:

```text
/tmp/nocturne-m3pv.OkV5dY/venv/bin/python -m pytest -q
......                                                                   [100%]
6 passed in 0.48s
```

Current seven-tool/fence contract plus the existing M3B golden slice:

```text
UV_CACHE_DIR=/tmp/n8-m3pv-focused-uv PYTHONPATH=src \
  uv run --locked pytest -q tests/test_pi_toolset.py tests/golden
...............                                                          [100%]
15 passed in 1.11s
```

The existing M3B goldens pin the model, broker, config, memory, and model-visible
tool schema surfaces. They do **not** pin the exact output of the seven coding
tools. `tests/test_pi_toolset.py` pins their main behavior and fences. That is a
blind spot, not permission to change output casually.

Full handoff grounds on the verification tree:

```text
Harness: 1681 passed, 3 deselected in 69.97s
Spine:    281 passed in 15.98s
```

## Smallest safe migration sketch

This is a map for a later owner-authorized packet, not work performed by M3PV.

1. First capture exact current outputs for `read`, `edit`, `write`, `grep`,
   `find`, `ls`, and `bash` as model-visible goldens. Include success, refusal,
   truncation/limit, empty result, and error cases.
2. Resolve the two functional gaps without rebuilding a second tool library:
   upstream context-line search support and a supported way for Skills to
   enumerate/read bundled resources. If upstream will not supply them, keep the
   current layer.
3. Run a separately scoped Pydantic AI 2.12-to-supported-floor compatibility
   packet. The runtime loop, broker, cancellation, journal, memory gate, spend,
   provider receipts, and browser path must stay behaviorally unchanged.
4. Only then replace the implementation behind `StandardToolset` with one
   owned adapter. Keep the seven schemas in `pydantic_ai_adapter.py`, the
   canonical location preflight, movement receipts, secret scrub, remote-state
   refusal, and macOS OS sandbox.
5. Retire, in the same atomic swap, `src/harness/_pi/`, `pi_runtime.py`, the PI
   RPC adapter and smoke script, `NOCTURNE_PI_COMMAND`, runtime download and
   onboarding code, packaging entries, and the PI updater. Update
   `pyproject.toml` and `uv.lock` with an exact candidate pin and recorded wheel
   digest.
6. Rename the current PI contract tests around the neutral adapter, run the new
   exact goldens, both full grounds, and owner browser proof before removing the
   old runtime. Do not adopt upstream subagents or compaction in this packet.

## Stop conditions before a swap packet may start

1. Search context and full skill-resource workflows have released, tested
   coverage without a locally recreated filesystem/search subsystem.
2. The Pydantic AI core upgrade has independent green compatibility evidence.
3. The owner reads this HOLD, reviews the new exact coding-tool goldens, and
   explicitly gives the final go.

M3PV changed no product source, dependency, lockfile, test contract, or runtime.
Its only Harness additions are this verdict and the disposable verification
prototype/slice.
