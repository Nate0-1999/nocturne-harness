"""Thin Harness ownership seam for the A-059 Symphony memory lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from harness.spine_client import (
    JudgedContext,
    MemoryKind,
    ResolveSymphonyRunRequest,
    ResolveSymphonyRunResponse,
    SpineClient,
    StageSymphonyMemoryRequest,
    StageSymphonyMemoryResponse,
    SymphonyVisibilityRequest,
    SymphonyVisibilityResponse,
)


@dataclass(frozen=True, slots=True)
class MemorySharePolicy:
    """Reserve a smaller context share for leaf attempts than for the conductor."""

    leaf: float = 0.05
    conductor: float = 0.10

    def __post_init__(self) -> None:
        if not 0 < self.leaf < self.conductor <= 1:
            raise ValueError("memory shares must satisfy 0 < leaf < conductor <= 1")

    def tokens(self, model_context_tokens: int, *, role: Literal["leaf", "conductor"]) -> int:
        if model_context_tokens <= 0:
            raise ValueError("model_context_tokens must be positive")
        return max(1, int(model_context_tokens * getattr(self, role)))


class SymphonyMemoryBridge:
    """Keep Symphony orchestration out of Spine while using its authoritative storage."""

    def __init__(
        self,
        spine: SpineClient,
        *,
        principal_id: str,
        machine_id: str,
        thread_id: UUID,
        shares: MemorySharePolicy | None = None,
    ) -> None:
        self._spine = spine
        self._principal_id = principal_id
        self._machine_id = machine_id
        self._thread_id = thread_id
        self.shares = shares or MemorySharePolicy()

    async def visible(self, *, run_id: str, origin_agent: str) -> SymphonyVisibilityResponse:
        return await self._spine.visible_symphony_memories(
            SymphonyVisibilityRequest(
                principal_id=self._principal_id,
                run_id=run_id,
                origin_agent=origin_agent,
            )
        )

    async def stage(
        self,
        *,
        memory_id: UUID,
        run_id: str,
        origin_agent: str,
        label: str,
        body: str,
        kind: MemoryKind,
        keywords: list[str] | None = None,
        project_key: str | None = None,
        origin_path: str | None = None,
    ) -> StageSymphonyMemoryResponse:
        return await self._spine.stage_symphony_memory(
            StageSymphonyMemoryRequest(
                memory_id=memory_id,
                principal_id=self._principal_id,
                label=label,
                body=body,
                kind=kind,
                keywords=[] if keywords is None else keywords,
                project_key=project_key,
                origin_thread_id=self._thread_id,
                origin_path=origin_path,
                run_id=run_id,
                origin_agent=origin_agent,
                machine_id=self._machine_id,
            )
        )

    async def resolve(
        self,
        *,
        run_id: str,
        batch_uid: UUID,
        winner_origin_agent: str,
        judged_context: JudgedContext,
    ) -> ResolveSymphonyRunResponse:
        return await self._spine.resolve_symphony_run(
            run_id,
            ResolveSymphonyRunRequest(
                principal_id=self._principal_id,
                batch_uid=batch_uid,
                winner_origin_agent=winner_origin_agent,
                machine_id=self._machine_id,
                judged_context=judged_context,
            ),
        )
