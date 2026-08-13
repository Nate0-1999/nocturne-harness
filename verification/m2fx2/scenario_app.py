"""Local fixture for the M2FX2 authoritative memory-write walkthrough."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import httpx
from fastapi import FastAPI
from pydantic_ai.models.test import TestModel

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.spine_client import (
    CreateMemoryConflictError,
    CreateMemoryRequest,
    CreateMemoryResponse,
    DuplicateMemoryConflict,
    ListMemoriesParams,
    MemoryKind,
    MemoryStatus,
    MemoryUnit,
    PagedMemoryListResponse,
    PatchMemoryRequest,
    PatchMemoryResponse,
    SimilarityMemoryCard,
)
from harness.transcript import TranscriptJournal
from verification.fixture_isolation import install_fixture_isolation
from verification.m2ux1.scenario_app import LayoutSpine

FIXTURE = "M2FX2 REGRESSION"
MEMORY_ID = UUID("f2000000-0000-4000-8000-000000000002")
UPDATED = datetime(2026, 8, 13, 16, 0, tzinfo=UTC)


def _memory(*, body: str, revision: int, reinforcements: int = 0) -> MemoryUnit:
    return MemoryUnit(
        memory_id=MEMORY_ID,
        principal_id="m2fx2-verification",
        label="Authoritative write rule",
        body=body,
        kind=MemoryKind.PROCEDURE,
        keywords=["memory", "authority", "write"],
        project_key="build-test",
        thread_origin=None,
        origin_path="verification/m2fx2",
        pin=False,
        status=MemoryStatus.ACTIVE,
        revision=revision,
        stats={"reinforcements": reinforcements},
        bias=0.0,
        embedding_model="fixture",
        created_at=UPDATED,
        updated_at=UPDATED,
    )


class WriteFlowSpine(LayoutSpine):
    """Return authoritative state for edit and duplicate reinforcement paths."""

    def __init__(self) -> None:
        super().__init__()
        self.memory = _memory(
            body="A write is visible only after its authoritative acknowledgement.",
            revision=1,
        )

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        items = [self.memory] if params.status in {None, MemoryStatus.ACTIVE} else []
        return PagedMemoryListResponse(
            items=items[params.offset : params.offset + params.limit],
            total=len(items),
            limit=params.limit,
            offset=params.offset,
        )

    async def create_memory(self, request: CreateMemoryRequest) -> CreateMemoryResponse:
        duplicate = SimilarityMemoryCard(
            memory_id=self.memory.memory_id,
            label=self.memory.label,
            body=self.memory.body,
            kind=self.memory.kind,
            pin=self.memory.pin,
            score=0.99,
            features=None,
            rank=None,
        )
        response = httpx.Response(409, request=httpx.Request("POST", "http://fixture/v1/memories"))
        raise CreateMemoryConflictError(
            response,
            DuplicateMemoryConflict(duplicate_of=duplicate),
        )

    async def patch_memory(
        self,
        memory_id: UUID,
        request: PatchMemoryRequest,
    ) -> PatchMemoryResponse:
        if memory_id != self.memory.memory_id or request.expected_revision != self.memory.revision:
            raise AssertionError("M2FX2 fixture received a stale or foreign memory patch")
        updates: dict[str, object] = {"revision": self.memory.revision + 1}
        if request.body is not None:
            updates["body"] = request.body
        if request.pin is not None:
            updates["pin"] = request.pin
        if request.reason == "remember/reinforce":
            count = self.memory.stats.get("reinforcements", 0)
            assert isinstance(count, int)
            updates["stats"] = {**self.memory.stats, "reinforcements": count + 1}
        self.memory = self.memory.model_copy(update=updates)
        return self.memory


def create_scenario_app() -> FastAPI:
    """Compose the owner surface with fixture-only identity and transcript storage."""

    settings = HarnessSettings(
        principal_id="m2fx2-verification",
        machine_id="m2fx2-verification",
        agent_id="m2fx2-verification",
        chat_model="local:m2fx2-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    model = TestModel(
        call_tools=[],
        custom_output_text=json.dumps(
            {"label": "Authoritative write rule", "keywords": ["memory", "authority"]}
        ),
    )
    workspace = TemporaryDirectory(prefix="nocturne-m2fx2-")
    journal = TranscriptJournal(Path(workspace.name) / "transcripts")
    conflict_thread_id = os.environ.get("M2FX2_CONFLICT_THREAD_ID", "").strip()
    if conflict_thread_id:
        UUID(conflict_thread_id)
        journal.append_thread_context(conflict_thread_id, "build-test")
    spine = WriteFlowSpine()
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=model),
        spine=spine,  # type: ignore[arg-type]
        transcript_journal=journal,
    )
    app = FastAPI(title="M2FX2 memory write-flow verification")
    app.state.fixture_workspace = workspace
    install_fixture_isolation(app, FIXTURE)

    @app.get("/__scenario__/state")
    async def fixture_state() -> dict[str, object]:
        return {
            "memory_id": str(spine.memory.memory_id),
            "body": spine.memory.body,
            "revision": spine.memory.revision,
            "stats": spine.memory.stats,
            "threads": [item.thread_id for item in journal.hydrate_threads()],
        }

    app.mount("/", harness_app)
    return app


__all__ = ["FIXTURE", "create_scenario_app"]
