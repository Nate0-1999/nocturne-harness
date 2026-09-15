"""Seed only M3WF's local corpus; gate dispositions are made in the browser."""

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from harness.spine_client import (
    CreateMemoryRequest,
    MemoryKind,
    PatchMemoryRequest,
    SpineClient,
)
from verification.m3wf.scenario_app import HOME, MACHINE, PRINCIPAL, fixture_config

CORPUS = [
    (
        "Orchard delivery day",
        "The fixture orchard delivers apples on Monday.",
        ["orchard", "apples"],
    ),
    (
        "Orchard delivery box",
        "The fixture orchard packs apples in blue boxes.",
        ["orchard", "apples"],
    ),
    (
        "Orchard delivery gate",
        "The fixture orchard delivery enters the north gate.",
        ["orchard", "delivery"],
    ),
    (
        "Orchard delivery driver",
        "The fixture orchard delivery driver is named Mina.",
        ["orchard", "delivery"],
    ),
    (
        "Telescope lens",
        "The fixture observatory telescope uses a glass lens.",
        ["observatory", "telescope"],
    ),
    (
        "Telescope schedule",
        "The fixture observatory opens its telescope on Friday.",
        ["observatory", "telescope"],
    ),
    (
        "Telescope notebook",
        "The fixture observatory records stars in a red notebook.",
        ["observatory", "stars"],
    ),
    ("Telescope guide", "The fixture observatory guide is named Omar.", ["observatory", "guide"]),
]


async def restore_recorded_history():
    """Replay recorded fixture taps, never relabel generated or owner events."""
    from spine.db.models import InjectionEvent, ScorerConfig
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.ext.asyncio import create_async_engine

    receipt = json.loads(Path(__file__).with_name("recorded-gates.json").read_text())
    assert receipt["fixture"] is True and receipt["principal"] == PRINCIPAL
    assert len(receipt["gates"]) >= 25
    assert all(
        row["principal_id"] == PRINCIPAL
        and row["machine_id"] == MACHINE
        and row["actor_class"] == "human"
        and row["outcome"] in {"kept", "cited", "removed:not_relevant"}
        for row in receipt["gates"]
    )
    engine = create_async_engine(fixture_config().database_url)
    try:
        async with engine.begin() as connection:
            for config in receipt["configs"]:
                config["active"] = False
                config["created_at"] = datetime.fromisoformat(config["created_at"])
                await connection.execute(
                    insert(ScorerConfig)
                    .values(**config)
                    .on_conflict_do_nothing(index_elements=["version"])
                )
            for event in receipt["gates"]:
                event.pop("id", None)
                event["ts"] = datetime.fromisoformat(event["ts"])
                for field in ("injection_id", "thread_id", "memory_id"):
                    event[field] = UUID(event[field])
                await connection.execute(
                    insert(InjectionEvent)
                    .values(**event)
                    .on_conflict_do_nothing(index_elements=["event_uid"])
                )
    finally:
        await engine.dispose()
    print(f"Restored {len(receipt['gates'])} original fixture tap records.")


async def main():
    config = fixture_config()
    HOME.mkdir(parents=True, exist_ok=True)
    client = SpineClient("http://127.0.0.1:8902", config.spine_token, principal_id=PRINCIPAL)
    records = []
    try:
        for label, body, keywords in CORPUS:
            result = await client.create_memory(
                CreateMemoryRequest(
                    principal_id=PRINCIPAL,
                    label=label,
                    body=body,
                    keywords=keywords,
                    kind=MemoryKind.FACT,
                    project_key=str(HOME / "workspace"),
                    origin_location=str(HOME / "workspace"),
                    editor="human:verification-fixture",
                    machine_id=MACHINE,
                    force=True,
                )
            )
            memory = result.created
            assert memory is not None
            pinned = await client.patch_memory(
                memory.memory_id,
                PatchMemoryRequest(
                    expected_revision=memory.revision,
                    pin=True,
                    editor="human:verification-fixture",
                    reason="M3WF pinned fixture corpus; relevance is judged at real gates",
                    machine_id=MACHINE,
                ),
            )
            records.append(pinned.model_dump(mode="json"))
        Path(HOME / "seed-receipt.json").write_text(
            json.dumps(
                {
                    "fixture": True,
                    "principal_id": PRINCIPAL,
                    "embedding": "deterministic lexical fixture, not a learned embedding model",
                    "dispositions": "none seeded; browser gate decisions must create them",
                    "memories": records,
                },
                indent=2,
            )
            + "\n"
        )
        print(f"Seeded {len(records)} fixture memories; zero fabricated gate dispositions.")
    finally:
        await client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recorded-history",
        action="store_true",
        help="restore the recorded browser decisions instead of creating memories",
    )
    args = parser.parse_args()
    asyncio.run(restore_recorded_history() if args.recorded_history else main())
