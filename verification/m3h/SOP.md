# M3H owner-turn verification

This proof joins PI's published tools to the existing owner-model loop. It uses
the production `create_dev_app` factory, a real OpenRouter response, an isolated
local Spine, and the checksummed PI 0.84.2 standalone executable. It does not use
the H5 scenario app, a fake model, owner identity, or durable owner memory.

## Isolated launch

Launch the contract Spine on a free non-default port with a unique Compose
project and disposable volume. Create a mode-0700 `NOCTURNE_HOME`, a disposable
project containing `notes/handoff.md`, and run the owner factory on another
confirmed-free loopback port with:

- verification-only principal, machine, and agent identifiers;
- `SPINE_URL` and its verification bearer token pointed at the isolated Spine;
- a real `OPENROUTER_API_KEY` supplied only in the owner process environment;
- `DEFAULT_MODEL=openrouter:minimax/minimax-m3`;
- `NOCTURNE_PI_COMMAND` pointed at the downloaded release executable; and
- the disposable project as the daemon's working directory.

No credential value belongs in shell output, the browser, the journal, or a
checked-in artifact.

## Owner edit

1. Open the normal Rack and create a new thread in the disposable project.
2. Ask Nocturne to move into `notes`, replace
   `Status: waiting for the owner agent.` with
   `Status: edited by the live Nocturne owner agent.`, read the file back, and
   report the exact change.
3. Require the real model to call the joined workspace capability. The recorded
   run produced seven paired function-tool call/result events: one `bash`, two
   `ls`, one `move`, two `read`, and one `edit`. All seven succeeded. The model
   used `pwd` despite an explicit request not to use bash, but the command ran in
   the OS sandbox, stayed in the current location, and was disclosed in its final
   answer.
4. Verify the actual file on disk contains the requested status and no other
   change. This reversible in-location edit correctly requires no consent gate.

## Rack and ledger

Reload the Rack after the run. Require the conversation to show the exact edit,
the journal gauge to be non-zero, and Spend to render server-provided total,
`building`, and model lanes. The recorded isolated ledger contains 27 receipt
lines totaling `$0.002573220000` for `minimax/minimax-m3`.

Context Bars must show the real model limit and label its basis. The recorded
view showed `2.3K / 1M`, including `Tools 1.2K`, with the note that tool traffic
is measured while other lane allocation remains estimated.

## Boundary smoke and cleanup

Run `uv run --locked python scripts/pi_toolset_smoke.py` once against the source
runtime and once with `NOCTURNE_PI_COMMAND` set to the standalone executable.
Both runs must create, edit, append, and read inside the current location; scrub
the synthetic process secret; and refuse an attempted write above the current
location.

Before deleting anything, record only counts, hashes, and credential-free facts
in `trace-summary.json`. Stop the exact owner process, remove only the named
Compose project and its disposable volumes, close the verification tab, and
remove only the validated temporary home/project tree. Update the cleanup booleans
in the trace after confirming each action. No live owner data is eligible for
cleanup under this SOP.
