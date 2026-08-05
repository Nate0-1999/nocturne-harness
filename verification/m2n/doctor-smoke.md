# M2N local doctor smoke — 2026-08-04

An isolated `NOCTURNE_HOME` and Compose project were created under
`/private/tmp`; no owner Palace, config, port, or volume was used.

- PostgreSQL image: the packaged A-041 OCI-index digest.
- Database port: loopback `55440`.
- Setup: initialized a private version-2 config, started only the isolated
  PostgreSQL service, and published one real `nocturne backup` generation.
- Command: `nocturne doctor` against the healthy isolated database.
- Result: exit 0 and `Palace doctor: healthy`.
- Measurements: database 7.3 MiB, journal 0 B, one verified backup totaling
  1.3 KiB, and filesystem free/total capacity.
- Verification: doctor recomputed the receipt digest and byte count, checked
  private modes, and streamed the archive through the pinned container's
  `pg_restore --list`.
- Cleanup: the isolated container, network, volume, fake config, and backup were
  removed after inspection.

Scripted verification in `tests/test_m2n_backup.py` additionally proves the
early disk warning/exit-1 boundary and failure/exit-2 behavior for a corrupted
recognized generation.
