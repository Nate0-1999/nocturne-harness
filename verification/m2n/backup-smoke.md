# M2N local backup smoke — 2026-08-04

An isolated `NOCTURNE_HOME` and Compose project were created under
`/private/tmp`; no owner Palace, config, port, or volume was used.

- PostgreSQL image: the packaged A-041 OCI-index digest.
- Database port: loopback `55439`.
- Command: `nocturne backup` against the healthy isolated database.
- Result: exit 0; one ULID generation published.
- Archive: PostgreSQL custom format, 858 bytes for the empty smoke database;
  the command's in-container `pg_restore --list` verification passed.
- Receipt: schema 1, `reason=manual`, `alembic_revision=null`, exact byte count,
  lowercase SHA-256, pinned image identity, no credentials.
- Permissions: backups root and generation `0700`; archive and receipt `0600`.
- Cleanup: the isolated container, network, volume, fake config, and backup were
  removed after inspection.

Scripted verification in `tests/test_m2n_backup.py` additionally proves that a
failed dump publishes no generation and retention ignores unrecognized paths.
