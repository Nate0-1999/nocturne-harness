"""Disposable real-Palace setup, ranking evidence, and cleanup for M3TL."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import UUID, uuid4

from harness.spine_client import (
    CreateMemoryRequest,
    InjectPrepareRequest,
    ListMemoriesParams,
    MemoryKind,
    MemoryStatus,
    PatchMemoryRequest,
    QueueDecisionRequest,
    SpineClient,
)

PRINCIPAL_ID = "m3tl-sop-verification"
MACHINE_ID = "m3tl-sop-verification"
ALPHA_THREAD_ID = UUID("a73f4c03-b91e-43b0-bb09-502122b44f92")
BETA_THREAD_ID = UUID("f6a2ed53-8414-4874-ba06-617d795e06d4")
ALPHA_LOCATION = "/private/tmp/nocturne-m3tl-tl02.japUC3/projects/alpha/nested"
BETA_LOCATION = "/private/tmp/nocturne-m3tl-tl02.japUC3/projects/beta"


def client() -> SpineClient:
    return SpineClient(os.environ["SPINE_URL"], os.environ["SPINE_TOKEN"])


async def rank() -> None:
    async with client() as spine:
        existing = await spine.list_memories(
            ListMemoriesParams(status=MemoryStatus.ACTIVE, limit=200)
        )
        existing_labels = {memory.label for memory in existing.items}
        created: list[object] = []
        specs = (
            (
                "M3TL locality pair amber",
                "M3TL locality pair amber: an alpha-nested witness recorded ALPHA-7.",
                ["m3tl", "locality", "amber", "alpha"],
                ALPHA_THREAD_ID,
                ALPHA_LOCATION,
            ),
            (
                "M3TL locality pair indigo",
                "M3TL locality pair indigo: beta folder proof carries BETA-9.",
                ["m3tl", "locality", "indigo", "beta"],
                BETA_THREAD_ID,
                BETA_LOCATION,
            ),
        )
        for label, body, keywords, thread_id, location in specs:
            if label in existing_labels:
                continue
            created.append(await spine.create_memory(CreateMemoryRequest(
                principal_id=PRINCIPAL_ID,
                label=label,
                body=body,
                kind=MemoryKind.FACT,
                keywords=keywords,
                project_key=None,
                thread_origin=str(thread_id),
                origin_thread_id=thread_id,
                origin_location=location,
                editor="human",
                machine_id=MACHINE_ID,
                force=False,
            )))
        memories = await spine.list_memories(
            ListMemoriesParams(status=MemoryStatus.ACTIVE, limit=200)
        )
        by_id = {memory.memory_id: memory for memory in memories.items}
        response = await spine.prepare_injection(
            InjectPrepareRequest(
                thread_id=uuid4(),
                agent_id="nocturne",
                machine_id=MACHINE_ID,
                principal_id=PRINCIPAL_ID,
                project_key=BETA_LOCATION,
                current_location=BETA_LOCATION,
                prompt=(
                    "M3TL locality pair amber indigo alpha nested beta folder proof "
                    "ALPHA-7 BETA-9"
                ),
                model_context_tokens=1_000_000,
            )
        )
        cards = [*response.injected, *response.near_misses]
        evidence = [
            {
                "rank": card.rank,
                "label": card.label,
                "score": card.score,
                "where": card.features.where,
                "origin_location": by_id[card.memory_id].origin_location,
            }
            for card in cards
            if card.label.startswith("M3TL locality pair")
        ]
        print(json.dumps({
            "created": [item.model_dump(mode="json") for item in created],
            "ranking": evidence,
        }, indent=2))


async def cleanup() -> None:
    async with client() as spine:
        queue = await spine.approval_queue(PRINCIPAL_ID)
        denied: list[str] = []
        for card in queue.cards:
            await spine.decide_queue_item(
                card.item_uid,
                QueueDecisionRequest(
                    decision="deny",
                    approval_mode="explicit",
                    actor_class="human",
                    machine_id=MACHINE_ID,
                ),
            )
            denied.append(card.item_uid)
        memories = await spine.list_memories(
            ListMemoriesParams(status=MemoryStatus.ACTIVE, limit=200)
        )
        tombstoned: list[str] = []
        for memory in memories.items:
            if memory.principal_id != PRINCIPAL_ID:
                continue
            await spine.patch_memory(
                memory.memory_id,
                PatchMemoryRequest(
                    expected_revision=memory.revision,
                    status=MemoryStatus.TOMBSTONED,
                    editor="human",
                    reason="M3TL disposable verification cleanup",
                    machine_id=MACHINE_ID,
                ),
            )
            tombstoned.append(str(memory.memory_id))
        print(json.dumps({
            "denied_queue_items": denied,
            "tombstoned": tombstoned,
            "count": len(tombstoned),
        }, indent=2))


async def approve_compaction() -> None:
    async with client() as spine:
        queue = await spine.approval_queue(
            PRINCIPAL_ID,
            thread_id=ALPHA_THREAD_ID,
            birthplace="thread",
        )
        card = next(
            card for card in queue.cards
            if card.candidate.label == "Folder-fence rule for edit tool"
        )
        decision = await spine.decide_queue_item(
            card.item_uid,
            QueueDecisionRequest(
                decision="approve",
                approval_mode="explicit",
                actor_class="human",
                machine_id=MACHINE_ID,
            ),
        )
        print(json.dumps({
            "decision": decision.decision,
            "label": decision.card.candidate.label,
            "origin_location": decision.card.candidate.origin_location,
            "state": decision.card.state,
        }, indent=2))


async def verify_cleanup() -> None:
    async with client() as spine:
        memories = await spine.list_memories(
            ListMemoriesParams(status=MemoryStatus.ACTIVE, limit=200)
        )
        queue = await spine.approval_queue(PRINCIPAL_ID)
        curator = await spine.curator_activity(PRINCIPAL_ID)
        print(json.dumps({
            "active_memories": sum(
                memory.principal_id == PRINCIPAL_ID for memory in memories.items
            ),
            "pending_queue_items": len(queue.cards),
            "pending_curator_cards": None if curator is None else curator.pending_cards,
        }, indent=2))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("rank", "approve-compaction", "cleanup", "verify-cleanup"),
    )
    args = parser.parse_args()
    if args.action == "rank":
        await rank()
    elif args.action == "approve-compaction":
        await approve_compaction()
    elif args.action == "verify-cleanup":
        await verify_cleanup()
    else:
        await cleanup()


if __name__ == "__main__":
    asyncio.run(main())
