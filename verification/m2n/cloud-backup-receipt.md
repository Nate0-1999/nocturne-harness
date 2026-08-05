# M2N owner-cloud pre-migration receipt

Date: 2026-08-04 America/Chicago (provider completion 2026-08-05 UTC)

## Safety boundary

This check created one on-demand backup of the fixed owner Cloud SQL instance
and exercised the exact receipt writer. It did not invoke Alembic, restore a
backup, delete a backup, change service traffic, or mutate any other cloud
resource.

## Deterministic ordering and failure evidence

`tests/test_deploy.py` proves both directions of the migration boundary:

- a successful create -> operation wait -> independent backup describe ->
  private receipt sequence completes before the packaged migration command;
- a mismatched or otherwise unverified backup stops before the proxy and
  migration command, and publishes no receipt.

The focused deployment/CLI suite passed: 143 tests.

## Live provider trace

- Project: `n8-memory-palace`
- Region/location: `us-central1`
- Instance: `n8-memory-palace-db`
- Database named by the receipt: `spine`
- Receipt ID: `01KZ7ZGBYZFMK3HB7FT9XYSRDR`
- Operation ID: `fa591228-16a5-4799-94b0-616200000032`
- Backup ID: `1785900577396`
- Description: `nocturne-pre-migration-01kz7zgbyzfmk3hb7ft9xysrdr`
- Independently described state: `SUCCESSFUL`, `ON_DEMAND`, `us-central1`
- Provider end time: `2026-08-05T03:30:28.162Z`
- Private locator: `NOCTURNE_HOME/cloud-backups/01KZ7ZGBYZFMK3HB7FT9XYSRDR.json`
- Receipt directory/file modes: `0700` / `0600`
- Receipt schema: exactly the 19 A-046 fields; no credential, command output,
  or restore claim is stored.

Google's GA Cloud SDK contract confirms that backup creation waits unless
`--async` is used. The implementation uses `--async` only to retain the exact
operation identity, waits on that operation for at most 30 minutes, and then
uses `gcloud sql backups describe` as the independent completed-backup check.

## Recovery statement

This receipt is evidence and a provider locator. Cloud restore remains an
explicit human Cloud SQL operation. M2N does not automate it and does not gain
cloud-backup deletion authority.
