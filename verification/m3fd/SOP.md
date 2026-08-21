# M3FD owner-path verification

Identity: `m3fd-sop-verification`  
Candidate bundle: `index-Ck3czM-B.js` (`97c1275551f25a85080740b77e0ae51b55bbcd7e7d7145caa3bc927307c71360`)  
App: real candidate Rack against the released Palace; no fixture server

## 1 — Leaving the Project field persists the accepted binding

**WHAT I DID:** In a fresh private home, I typed `m3fd-accept-fd21` over the
default Project value and moved focus out of the field without pressing Enter.

**WHAT I EXPECTED:** The ordinary end-of-edit gesture would use the existing
project-open request, and the Rack would show the new value only after the
daemon durably accepted it.

**WHAT I SAW:** The Rack moved to thread
`5c3ed619-2f92-4344-aa2a-6e3804235e0a`, rendered
`m3fd-accept-fd21`, and its first journal row is the matching
`thread_context`. Reload rendered the same thread and project. Screenshot:
`01-project-accepted.png`.

**WHY IT MATTERS:** Clicking away can no longer leave an optimistic project
name over an unchanged durable binding. [P2; F056; ADR-016]

## 2 — A sibling project selects zero project-local memories

**WHAT I DID:** In the accepted project, I saved one disposable project-local
memory through `/remember`. I then typed `m3fd-sibling-fd21`, moved focus out
of the field, and sent one ordinary first-turn prompt in the resulting sibling
thread.

**WHAT I EXPECTED:** The sibling thread would durably own its displayed
project, and the existing Spine project fence would exclude the first
project's memory before scoring.

**WHAT I SAW:** Thread `72c65e1a-632a-476e-9788-5590c00e8dc2` begins with
durable `thread_context.project_key = m3fd-sibling-fd21`. Gate
`834cbde6-ee31-48b5-85ff-814a545d4adc` returned exact empty `injected` and
`near_misses` arrays; the owner surface said `0 selected`, `0 added`, and
`0 memories will be used`. Screenshot: `02-sibling-zero-memory-gate.png`.
The unnecessary post-gate tool search was cancelled after the fence was
proved; no answer is used as isolation evidence.

**WHY IT MATTERS:** The fix restores truth at the Rack binding without
touching or taking credit for the memory system, which already behaved
correctly on durable inputs. [P2; F056; D.2 121]

## 3 — Thread switch, reload, and cleanup retain one truth

**WHAT I DID:** I switched back by typing `m3fd-accept-fd21` and moving focus
out, then inspected the returned thread and tombstoned the exact verification
memory by UUID.

**WHAT I EXPECTED:** The existing project thread would return with its durable
binding and history, while cleanup would leave no active verification memory.

**WHAT I SAW:** The Rack returned to the original `5c3ed619…` thread, rendered
`m3fd-accept-fd21`, and showed its `/remember` history. The exact unit
`754d6682-7a01-4630-b3f5-5bcbc6529420` moved from active revision 1 to
tombstoned revision 2; a Rack refresh showed `0 ACTIVE UNITS` and
`NO ACTIVE MEMORIES`. Screenshots: `03-thread-switch-return.png` and
`04-cleanup-zero-active.png`. The browser console had zero warnings or errors.

**WHY IT MATTERS:** Acceptance, reload, thread switching, and cleanup all read
from durable authority instead of preserving a browser-only project story.
[P2; F056; ADR-016]
