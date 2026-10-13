"""ADR-003 degraded offline mode proofs for the M4BW local Palace copy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from harness.memory_panel import ThreadMemoryContextRegistry
from harness.palace_mirror import PalaceMirror
from harness.spine_client import (
    InjectPrepareRequest,
    ListMemoriesParams,
    MemoryUnit,
    PagedMemoryListResponse,
    ScorerConsoleQuery,
    ScorerConsoleSnapshot,
    SpineTransportError,
)

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
PRINCIPAL = "principal-1"
FERRY = UUID("00000000-0000-4000-8000-0000000000f1")
BELL = UUID("00000000-0000-4000-8000-0000000000b1")
PEER = UUID("00000000-0000-4000-8000-0000000000a1")


def unit(
    memory_id: UUID,
    label: str,
    body: str,
    *,
    principal: str = PRINCIPAL,
    project: str | None = "/work/harbour",
) -> MemoryUnit:
    return MemoryUnit(
        memory_id=memory_id,
        principal_id=principal,
        label=label,
        body=body,
        kind="fact",
        keywords=label.lower().split(),
        project_key=project,
        thread_origin=None,
        origin_thread_id=None,
        origin_path=None,
        pin=False,
        status="active",
        revision=1,
        stats={"citations": 0},
        bias=0.0,
        embedding_model="openai/text-embedding-3-small",
        created_at=NOW,
        updated_at=NOW,
    )


class FakePalace:
    def __init__(self, *, console_fails: bool = False) -> None:
        self.console_fails = console_fails
        self.units = [
            unit(
                FERRY, "Cobble Quay ferry", "The Cobble Quay ferry rests on Christmas Day."
            ),
            unit(BELL, "Vela bell", "The Vela observatory rings a bell at noon.", project=None),
            unit(PEER, "Cobble Quay ferry", "A peer's memory.", principal="someone-else"),
        ]

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        return PagedMemoryListResponse(items=self.units, total=len(self.units), limit=200, offset=0)

    async def scorer_console(self, request: ScorerConsoleQuery) -> ScorerConsoleSnapshot:
        if self.console_fails:
            raise SpineTransportError
        recipe = {
            "version": "m3tl-where-v1",
            "status": "active",
            "values": {
                "tau": 0.4,
                "top_k": 8,
                "memory_context_share": 0.1,
                "half_life_time_days": 14,
                "half_life_hist_days": 30,
                "weights": {
                    "sem": 0.5,
                    "kw": 0.2,
                    "time": 0.1,
                    "proj": 0.1,
                    "freq": 0.05,
                    "hist": 0.05,
                },
            },
        }
        return ScorerConsoleSnapshot(
            as_of=NOW,
            scope="GLOBAL",
            thread_id=None,
            descriptors=[],
            active_version="m3tl-where-v1",
            configurations=[recipe],
            activations=[],
            proposed_versions=[],
            accuracy=[],
            learning={},
            candidates=[],
        )


def request(prompt: str) -> InjectPrepareRequest:
    return InjectPrepareRequest(
        thread_id=UUID("00000000-0000-4000-8000-000000000001"),
        agent_id="agent",
        machine_id="machine",
        principal_id=PRINCIPAL,
        project_key="/work/harbour",
        prompt=prompt,
        model_context_tokens=100_000,
    )


@pytest.mark.asyncio
async def test_the_copy_scores_the_first_turn_without_semantics_and_binds_its_block(
    tmp_path: Path,
) -> None:
    """ADR-003: offline, the prompt embedding needs the cloud, so f_sem is zero and the other
    weights are renormalized; only the principal's own active memories are copied.
    """
    mirror = PalaceMirror(tmp_path / "copy.sqlite3", clock=lambda: NOW)
    await mirror.refresh(FakePalace(), PRINCIPAL)

    prepared = mirror.prepare(request("When does the Cobble Quay ferry not sail?"))

    assert prepared is not None
    assert mirror.as_of() == NOW and mirror.memory_count() == 2
    assert prepared.scorer_version == "local copy · m3tl-where-v1"
    assert [card.memory_id for card in prepared.injected] == [FERRY]
    assert [card.memory_id for card in prepared.near_misses] == [BELL]
    assert all(card.features.sem == 0.0 for card in (*prepared.injected, *prepared.near_misses))
    block = mirror.final_block(prepared, removed=frozenset(), added_back=[BELL])
    snapshot = ThreadMemoryContextRegistry().install(
        "thread",
        prepared=prepared,
        removed_memory_ids=frozenset(),
        added_back=[BELL],
        final_block=block,
        from_local_copy=True,
    )
    assert snapshot.member_ids == {FERRY, BELL}
    assert snapshot.event_sources == {} and snapshot.from_local_copy


@pytest.mark.asyncio
async def test_no_copy_means_no_local_check_and_a_failed_refresh_keeps_the_old_copy(
    tmp_path: Path,
) -> None:
    """ADR-003: the copy is read-through; a refresh that cannot reach the Palace changes nothing."""
    mirror = PalaceMirror(tmp_path / "copy.sqlite3", clock=lambda: NOW)
    assert mirror.prepare(request("ferry")) is None

    await mirror.refresh(FakePalace(), PRINCIPAL)
    with pytest.raises(SpineTransportError):
        await PalaceMirror(tmp_path / "copy.sqlite3").refresh(
            FakePalace(console_fails=True), PRINCIPAL
        )

    assert mirror.as_of() == NOW and mirror.memory_count() == 2


@pytest.mark.asyncio
async def test_a_memory_waiting_to_be_deleted_is_not_offered_again(tmp_path: Path) -> None:
    """F175 / ADR-003: a ×! delete queued offline keeps the memory out of the next local check."""
    mirror = PalaceMirror(tmp_path / "copy.sqlite3", clock=lambda: NOW)
    await mirror.refresh(FakePalace(), PRINCIPAL)

    prepared = mirror.prepare(request("Cobble Quay ferry"), excluded=frozenset({FERRY}))

    assert prepared is not None
    assert FERRY not in {card.memory_id for card in (*prepared.injected, *prepared.near_misses)}
