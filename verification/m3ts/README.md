# M3TS verification

This evidence records the tool-layer swap from the PI subprocess to
`pydantic-ai-harness` capabilities behind the existing Harness seam.

## Two-stage golden proof

- After upgrading Pydantic AI to 2.28.0, before swapping the adapter: `159 passed in
  4.09s` across the golden, agent, runtime, daemon, and current-toolset slice.
- After the in-process adapter swap: the focused golden and adapter slice passed
  (`22 passed in 1.37s` after the final import-fence correction).
- The final full-suite commands and counts are recorded in the Garden handoff report.

## Real owner-path walk

On 2026-08-24 the source app ran at `http://127.0.0.1:8765` with a temporary
verification identity and the real configured model
`openrouter:minimax/minimax-m3`. Through the visible Rack, the owner prompt required
the agent to move into `child`, write `proof.txt`, then read it back.

The persisted transcript recorded these successful calls in order:

1. `move({"path":"child"})` returned
   `Moved to /private/tmp/nocturne-m3ts-ts24/workspace/child.`
2. `write({"path":"proof.txt","content":"M3TS in-process fence works"})`
   returned `Wrote 27 chars (1 lines) to proof.txt. [hash:7a0cfc6b4d65]`.
3. `read({"path":"proof.txt"})` returned the exact one-line content with the same
   short hash.

An independent disk read measured 27 bytes and SHA-256
`7a0cfc6b4d6545e03a471b65dc12f0e1338366ce3bced400dab86bc6d4721ba4`.
The browser displayed the same location, content, length, and short hash. No fixture
or deterministic scenario server was used.

## Honest output deltas

The pre-swap PI tools on this host could read, write, edit, run shell commands, and
list files, but `grep` failed when `rg` was unavailable and `find` failed when `fd`
was unavailable. The new in-process layer is dependency-free for both operations.
It also adds line numbers and hashes to reads, hashes to writes and edits, byte sizes
to directory listings, and labeled stdout/stderr to shell results. Exact
model-visible outputs are pinned in `tests/golden/test_workspace_tool_outputs.py`.

## Payload proof

The final clean-commit wheel was 934,617 bytes with SHA-256
`4dce2116475de0fbeabceb054c547f1686093bb68292d698637da01741ba92dd`.
Archive inspection found no `_pi`, `node_modules`, `pi_runtime`, or `pi_toolset`
payload. The removed ignored `_pi/node_modules` tree was 139 MB; the tracked PI
adapter remains recoverable from git history.
