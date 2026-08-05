"""A-045 real-container proof of informed side-by-side local restore."""

from __future__ import annotations

import io
import json
import socket
from pathlib import Path
from tempfile import TemporaryDirectory

from harness import lifecycle, onboarding

MEMORY_A = "11111111-1111-4111-8111-111111111111"
MEMORY_B = "22222222-2222-4222-8222-222222222222"
MEMORY_C = "33333333-3333-4333-8333-333333333333"


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _psql(config: onboarding.NocturneConfig, sql: str) -> str:
    with lifecycle._compose_command(config) as compose:
        result = lifecycle._run(
            [
                *compose,
                "exec",
                "--no-TTY",
                "postgres",
                "psql",
                "--username",
                "spine",
                "--dbname",
                "spine",
                "--tuples-only",
                "--no-align",
                "--command",
                sql,
            ],
            stdout=lifecycle.subprocess.PIPE,
            text=True,
        )
    return str(result.stdout).strip()


def _seed_before_backup(config: onboarding.NocturneConfig) -> None:
    _psql(
        config,
        f"""
        INSERT INTO memory_unit
          (id, principal_id, label, body, kind, keywords, embedding,
           embedding_model, pin, status, revision)
        VALUES
          ('{MEMORY_A}', 'local', 'Stable original', 'original body', 'fact',
           ARRAY['stable'], array_fill(0::real, ARRAY[1536])::vector,
           'openai/text-embedding-3-small', false, 'active', 1),
          ('{MEMORY_B}', 'local', 'Later pin', 'pin body', 'fact',
           ARRAY['pin'], array_fill(0::real, ARRAY[1536])::vector,
           'openai/text-embedding-3-small', false, 'active', 1);
        INSERT INTO memory_revision
          (rev_uid, memory_id, revision, body, label, editor,
           origin_machine_id, reason)
        VALUES
          ('01J00000000000000000000001', '{MEMORY_A}', 1, 'original body',
           'Stable original', 'user', 'restore-smoke', 'seed'),
          ('01J00000000000000000000002', '{MEMORY_B}', 1, 'pin body',
           'Later pin', 'user', 'restore-smoke', 'seed');
        """,
    )


def _mutate_after_backup(config: onboarding.NocturneConfig) -> None:
    _psql(
        config,
        f"""
        UPDATE memory_unit SET body='edited body', revision=2, updated_at=now()
          WHERE id='{MEMORY_A}';
        INSERT INTO memory_revision
          (rev_uid, parent_uid, memory_id, revision, body, label, editor,
           origin_machine_id, reason)
        VALUES ('01J00000000000000000000003', '01J00000000000000000000001',
          '{MEMORY_A}', 2, 'edited body', 'Stable original', 'user',
          'restore-smoke', 'edit');
        UPDATE memory_unit SET pin=true, revision=2, updated_at=now()
          WHERE id='{MEMORY_B}';
        INSERT INTO memory_revision
          (rev_uid, parent_uid, memory_id, revision, body, label, editor,
           origin_machine_id, reason)
        VALUES ('01J00000000000000000000004', '01J00000000000000000000002',
          '{MEMORY_B}', 2, 'pin body', 'Later pin', 'user',
          'restore-smoke', 'pin');
        INSERT INTO memory_unit
          (id, principal_id, label, body, kind, keywords, embedding,
           embedding_model, pin, status, revision)
        VALUES ('{MEMORY_C}', 'local', 'Born after backup', 'later body', 'fact',
          ARRAY['later'], array_fill(0::real, ARRAY[1536])::vector,
          'openai/text-embedding-3-small', false, 'active', 1);
        INSERT INTO memory_revision
          (rev_uid, memory_id, revision, body, label, editor,
           origin_machine_id, reason)
        VALUES ('01J00000000000000000000005', '{MEMORY_C}', 1, 'later body',
          'Born after backup', 'user', 'restore-smoke', 'seed');
        """,
    )


def main() -> None:
    with TemporaryDirectory(prefix="nocturne-restore-smoke-") as directory:
        home = Path(directory)
        config = onboarding.NocturneConfig(
            home=home,
            openrouter_api_key="smoke-only",
            spine_token="smoke-token",
            database_password="smoke-password",
            machine_id="restore-smoke",
            postgres_port=_free_port(),
        )
        onboarding._write_config(config)
        config = onboarding.load_config(home=home)
        volumes = {config.active_postgres_volume}
        prepared: lifecycle.PreparedRestore | None = None
        switched = False
        output = io.StringIO()
        try:
            with lifecycle._compose_command(config) as compose:
                lifecycle._run(
                    [*compose, "up", "--detach", "--wait", "postgres"],
                    stdout=lifecycle.subprocess.DEVNULL,
                )
            onboarding._upgrade_database(config.database_url)
            _seed_before_backup(config)
            generation = lifecycle.create_local_backup(config, reason="manual")
            _mutate_after_backup(config)

            prepared = lifecycle.prepare_local_restore(config, generation.name)
            volumes.add(prepared.candidate_volume)
            onboarding._print_rollback_manifest(prepared, stdout=output)
            assert [item.memory_id for item in prepared.manifest.memories_lost] == [MEMORY_C]
            assert {item.memory_id for item in prepared.manifest.edits_reverted} == {
                MEMORY_A,
                MEMORY_B,
            }
            assert [item.memory_id for item in prepared.manifest.pins_undone] == [MEMORY_B]

            receipt = lifecycle.activate_local_restore(
                config,
                prepared,
                set_active_volume=lambda volume: onboarding._set_active_postgres_volume(
                    config, volume
                ),
            )
            switched = True
            active = onboarding.load_config(home=home)
            restored = json.loads(
                _psql(
                    active,
                    "SELECT json_agg(json_build_object('id',id::text,'body',body,'pin',pin) "
                    "ORDER BY id)::text FROM memory_unit",
                )
            )
            assert [row["id"] for row in restored] == [MEMORY_A, MEMORY_B]
            assert restored[0]["body"] == "original body"
            assert restored[1]["pin"] is False
            assert receipt.is_file()
            assert lifecycle.stat.S_IMODE(receipt.stat().st_mode) == 0o600
            receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
            assert receipt_payload["former_volume"] == config.active_postgres_volume
            assert receipt_payload["active_volume"] == active.active_postgres_volume
            print(output.getvalue(), end="")
            print(
                json.dumps(
                    {
                        "backup_id": generation.name,
                        "former_volume_retained": config.active_postgres_volume,
                        "active_volume": active.active_postgres_volume,
                        "rollback_receipt": receipt.name,
                        "restored_memory_ids": [row["id"] for row in restored],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        finally:
            if prepared is not None and not switched:
                lifecycle.discard_prepared_restore(prepared)
            latest = onboarding.load_config(home=home)
            with lifecycle._compose_command(latest) as compose:
                lifecycle._cleanup_command([*compose, "down", "--remove-orphans"])
            for volume in volumes:
                lifecycle._cleanup_command(["docker", "volume", "rm", volume])


if __name__ == "__main__":
    main()
