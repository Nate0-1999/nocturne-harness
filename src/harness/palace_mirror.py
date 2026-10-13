"""M4BW (SD-082, FL-165): a read-only local copy of what injection needs.

While the cloud Palace answers, the copy holds the principal's active memories and the active
recipe. When it does not, the first-turn memory check is scored from the copy by the Palace's
own scorer, degraded as SPEC's offline mode says: the prompt embedding needs the cloud, so the
semantic weight is dropped and the other weights renormalized. The copy is disposable; the
Palace stays the one authority and rebuilds it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel
from spine.inject.renderer import render_final_block
from spine.inject.scorer import ScorerConfig, ScoringCandidate, score_and_select

from harness.memory_outbox import QueuedWrite, ReturnedWrite
from harness.spine_client import (
    InjectPrepareRequest,
    InjectPrepareResponse,
    ListMemoriesParams,
    MemoryAllocation,
    MemoryFeatures,
    MemoryStatus,
    MemoryUnit,
    PagedMemoryListResponse,
    ScoredMemoryCard,
    ScorerConsoleQuery,
    ScorerConsoleSnapshot,
)

# SPEC degraded offline mode: semantic scoring is off; orthogonal vectors make f_sem zero.
_NO_SEMANTIC_QUERY = (1.0, 0.0)
_NO_SEMANTIC_MEMORY = (0.0, 1.0)
_NEAR_MISS_K = 3  # the glossary's near-miss count; the console does not echo it


class LocalCopySnapshot(BaseModel):
    """What Palace State shows: the copy's age and the writes waiting or returned."""

    as_of: datetime | None
    memories: int
    waiting: list[QueuedWrite]
    returned: list[ReturnedWrite]


class MirrorGateway(Protocol):
    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse: ...

    async def scorer_console(self, request: ScorerConsoleQuery) -> ScorerConsoleSnapshot: ...


class PalaceMirror:
    """One SQLite file under the Nocturne home, replaced whole on every refresh."""

    def __init__(self, path: Path, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.path = path
        self._clock = clock

    async def refresh(self, spine: MirrorGateway, principal_id: str) -> None:
        """Copy every active memory and the active recipe; a failed read keeps the old copy."""

        units: list[MemoryUnit] = []
        offset = 0
        while True:
            page = await spine.list_memories(
                ListMemoriesParams(status=MemoryStatus.ACTIVE, limit=200, offset=offset)
            )
            units.extend(item for item in page.items if item.principal_id == principal_id)
            if not page.items or offset + len(page.items) >= page.total:
                break
            offset += len(page.items)
        console = await spine.scorer_console(
            ScorerConsoleQuery(principal_id=principal_id, thread_id=None)
        )
        recipe = next(
            item for item in console.configurations if item.get("version") == console.active_version
        )
        self._write(units, recipe, self._clock())

    def as_of(self) -> datetime | None:
        meta = self._meta()
        return None if meta is None else datetime.fromisoformat(meta["as_of"])

    def memory_count(self) -> int:
        if not self.path.exists():
            return 0
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT count(*) FROM memory").fetchone()[0]

    def prepare(
        self, request: InjectPrepareRequest, *, excluded: frozenset[UUID] = frozenset()
    ) -> InjectPrepareResponse | None:
        """Score the first-turn memory check from the copy, or None when there is no copy."""

        meta = self._meta()
        if meta is None:
            return None
        recipe = json.loads(meta["recipe"])
        units = [unit for unit in self._units() if unit.memory_id not in excluded]
        candidates = [_candidate(unit) for unit in units]
        selection = score_and_select(
            prompt=request.prompt,
            query_embedding=_NO_SEMANTIC_QUERY,
            snapshot_ts=self._clock(),
            thread_project_key=request.project_key,
            thread_id=request.thread_id,
            location_path=request.location_path,
            current_location=request.current_location,
            pinned_candidates=[item for item in candidates if item.pin],
            regular_candidates=[item for item in candidates if not item.pin],
            model_context_tokens=request.model_context_tokens,
            config=_degraded_config(recipe, pool=max(1, len(candidates))),
        )
        return InjectPrepareResponse(
            injection_id=uuid4(),
            snapshot_ts=datetime.fromisoformat(meta["as_of"]),
            scorer_version=f"local copy · {recipe['version']}",
            injected=[_card(item) for item in selection.injected],
            near_misses=[_card(item) for item in selection.near_misses],
            final_block=None,
            memory_allocation=MemoryAllocation(
                memory_context_share=float(recipe["values"]["memory_context_share"]),
                share_tokens=selection.regular_budget,
                regular_tokens=selection.regular_token_cost,
                pinned_tokens=selection.pin_token_cost,
                total_tokens=selection.total_token_cost,
                pinned_overflow_tokens=selection.pinned_overflow_tokens,
            ),
        )

    def final_block(
        self,
        prepared: InjectPrepareResponse,
        *,
        removed: frozenset[UUID],
        added_back: Sequence[UUID],
    ) -> str:
        """Render the chosen cards with the Palace's own C.6 renderer."""

        updated = {unit.memory_id: unit.updated_at for unit in self._units()}
        chosen = [card for card in prepared.injected if card.memory_id not in removed] + [
            card for card in prepared.near_misses if card.memory_id in set(added_back)
        ]
        return render_final_block(
            [
                {
                    "rank": card.rank,
                    "memory_id": card.memory_id,
                    "memory_kind": card.kind.value,
                    "features": {
                        "_memory": {
                            "label": card.label,
                            "body": card.body,
                            "updated_at": updated[card.memory_id].isoformat(),
                        }
                    },
                }
                for card in chosen
            ]
        )

    def _write(self, units: Sequence[MemoryUnit], recipe: Mapping[str, Any], as_of: datetime):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS memory (memory_id TEXT PRIMARY KEY, unit TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("DELETE FROM memory")
            db.executemany(
                "INSERT INTO memory VALUES (?, ?)",
                [(str(unit.memory_id), unit.model_dump_json()) for unit in units],
            )
            db.executemany(
                "INSERT OR REPLACE INTO meta VALUES (?, ?)",
                [("as_of", as_of.isoformat()), ("recipe", json.dumps(recipe))],
            )

    def _meta(self) -> dict[str, str] | None:
        if not self.path.exists():
            return None
        with sqlite3.connect(self.path) as db:
            meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
        return meta if {"as_of", "recipe"} <= set(meta) else None

    def _units(self) -> list[MemoryUnit]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT unit FROM memory").fetchall()
        return [MemoryUnit.model_validate_json(row[0]) for row in rows]


def _degraded_config(recipe: Mapping[str, Any], *, pool: int) -> ScorerConfig:
    values = recipe["values"]
    weights = {name: float(value) for name, value in values["weights"].items()}
    rest = 1.0 - weights["sem"]
    others = ("kw", "time", "proj", "freq", "hist")
    renormalized = {name: weights[name] / rest if rest > 0 else 1 / len(others) for name in others}
    return ScorerConfig.from_mappings(
        version=f"local copy · {recipe['version']}",
        weights={"sem": 0.0, **renormalized},
        params={
            "tau": values["tau"],
            "near_miss_k": _NEAR_MISS_K,
            "memory_context_share": values["memory_context_share"],
            "half_life_time_days": values["half_life_time_days"],
            "half_life_hist_days": values["half_life_hist_days"],
            "candidate_pool": pool,
        },
    )


def _candidate(unit: MemoryUnit) -> ScoringCandidate:
    return ScoringCandidate(
        memory_id=unit.memory_id,
        label=unit.label,
        body=unit.body,
        kind=unit.kind.value,
        keywords=tuple(unit.keywords),
        embedding=_NO_SEMANTIC_MEMORY,
        project_key=unit.project_key,
        origin_thread_id=unit.origin_thread_id,
        origin_path=unit.origin_path,
        origin_location=unit.origin_location,
        pin=unit.pin,
        updated_at=unit.updated_at,
        last_human_edit_at=None,
        stats=unit.stats,
        bias=unit.bias,
        revision=unit.revision,
    )


def _card(item) -> ScoredMemoryCard:
    candidate = item.candidate
    return ScoredMemoryCard(
        memory_id=candidate.memory_id,
        label=candidate.label,
        body=candidate.body,
        kind=candidate.kind,
        pin=candidate.pin,
        score=item.score,
        features=MemoryFeatures(**asdict(item.features)),
        rank=item.rank,
    )


__all__ = ["LocalCopySnapshot", "MirrorGateway", "PalaceMirror"]
