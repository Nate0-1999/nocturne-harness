# M2N informed restore evidence

Date: 2026-08-04

`verification/m2n/restore_smoke.py` exercised the real pinned PostgreSQL image,
packaged Alembic migration path, custom-format backup, candidate volume,
rollback inventory, Compose switch, and rollback receipt in an isolated
temporary `NOCTURNE_HOME`.

The source Palace contained two memories at backup time. After backup it gained
one memory, edited one existing body, and pinned the other. The manifest named:

- one memory lost: `Born after backup`;
- two edits reverted: revisions 2 to 1;
- one pin undone: `Later pin`;
- `memory_revision` changing from 5 to 2, with the other five event tables
  truthfully remaining 0 to 0.

After the confirmed switch, only the two backed-up memory IDs remained, the
edited body returned to its original value, and the later pin was false. The
mode-0600 rollback receipt named both the retained former volume and the active
restored volume. Final Docker inspection found no labeled restore containers or
volumes after cleanup.

Result: PASS.
