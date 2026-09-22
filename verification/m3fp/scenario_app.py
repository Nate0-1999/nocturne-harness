"""Deterministic packaged-asset core-loop heartbeat for CI and handoffs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.onboarding import nocturne_home
from harness.packaged import _runtime_web_assets
from harness.spine_client import (
    ExtractionResponse,
    InjectCommitRequest,
    InjectCommitResponse,
    InjectPrepareRequest,
    InjectPrepareResponse,
    MemoryAllocation,
    SpendEventsRequest,
    SpendEventsResponse,
)
from harness.transcript import TranscriptJournal
from verification.fixture_isolation import install_fixture_isolation
from verification.m2st3.scenario_app import HonestDisplaySpine

FIXTURE = "M3FP REGRESSION"
PROMPT = "Open the memory gate, then answer the heartbeat check."
ANSWER = (
    "M2H final post: the relay stays explicit, candidates remain reviewable, "
    "and contradictions never passively resolve."
)
TOOL_PROMPT = "Explain, read the heartbeat fixture, then explain the result."
TOOL_BEFORE = "I will read the fixture.\n\n"
TOOL_AFTER = "The file contains M3FZ-HEARTBEAT.\n\n"
ERROR_PROMPT = "Show the heartbeat failure reason."


def _model() -> FunctionModel:
    def extract(messages, info):
        return ModelResponse(
            [
                TextPart(
                    json.dumps(
                        {
                            "working_summary": "The heartbeat gate and tool round trip succeeded.",
                            "open_loops": [],
                            "candidates": [],
                        }
                    )
                )
            ]
        )

    async def stream(messages, _info):
        prompt = next(
            part.content
            for message in reversed(messages)
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        if prompt == ERROR_PROMPT:
            yield "The partial answer is preserved."
            raise RuntimeError("The heartbeat model stopped unexpectedly.")
        if prompt != TOOL_PROMPT:
            yield "<mm:thi"
            yield "nk>Private heartbeat reasoning.</mm:think>"
            yield ANSWER
        elif any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            yield TOOL_AFTER
            yield '<nocturne-proposed-response>{"primary":"Check it again.",'
            yield '"alternatives":[]}</nocturne-proposed-response>'
        else:
            yield TOOL_BEFORE
            yield {
                0: DeltaToolCall(
                    name="read",
                    json_args='{"path":"verification/m3fp/scenario_app.py"}',
                    tool_call_id="m3fz-heartbeat-read",
                )
            }

    return FunctionModel(function=extract, stream_function=stream)


class HeartbeatSpine(HonestDisplaySpine):
    """Count the exact Palace boundaries required by the standing heartbeat."""

    def __init__(self) -> None:
        super().__init__()
        self.prepare_calls = 0
        self.commit_calls = 0
        self.receipt_lines = 0
        self.compactions = 0

    async def create_extraction(self, request) -> ExtractionResponse:
        return ExtractionResponse(cards=[], duplicate_count=0)

    async def notify_compaction(self, event_uid, thread_id) -> None:
        self.compactions += 1

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        self.prepare_calls += 1
        return InjectPrepareResponse(
            injection_id=uuid4(),
            snapshot_ts=datetime.now(UTC),
            scorer_version="m3fp-heartbeat-v1",
            injected=[],
            near_misses=[],
            final_block=None,
            memory_allocation=MemoryAllocation(
                memory_context_share=0.10,
                share_tokens=100,
                regular_tokens=0,
                pinned_tokens=0,
                total_tokens=0,
                pinned_overflow_tokens=0,
            ),
        )

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse:
        self.commit_calls += 1
        return await super().commit_injection(request)

    async def record_spend_events(self, request: SpendEventsRequest) -> SpendEventsResponse:
        self.receipt_lines += len(request.events)
        return await super().record_spend_events(request)


def create_scenario_app() -> FastAPI:
    """Serve the real packaged asset resolution with deterministic local dependencies."""

    settings = HarnessSettings(
        principal_id="m3fp-heartbeat",
        machine_id="m3fp-heartbeat",
        agent_id="m3fp-heartbeat",
        chat_model="local:m3fp-heartbeat",
        # FL-198: a real-sized window; at 4,096 tokens the share cut the heartbeat's own read.
        model_context_tokens=200_000,
        extraction_idle_hours=None,
    )
    spine = HeartbeatSpine()
    journal = TranscriptJournal(nocturne_home() / "transcripts")
    # F088: a reinstall must tolerate old empty and unscoped files beside real history.
    for thread_id, raw in (("empty-leftover", ""), ("unscoped-leftover", "{}\n[]\n{\n")):
        path = journal.path_for_thread(thread_id)
        if not path.exists():
            path.write_text(raw, encoding="utf-8")
    web_dist, refusal = _runtime_web_assets()
    harness_app = create_dev_app(
        web_dist,
        missing_web_message=refusal or "The packaged Rack is unavailable.",
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=spine,  # type: ignore[arg-type]
        transcript_journal=journal,
    )
    app = FastAPI(title="M3FP packaged core-loop heartbeat")
    install_fixture_isolation(app, FIXTURE)

    @app.get("/__scenario__/heartbeat")
    async def heartbeat() -> dict[str, Any]:
        conversations = []
        for entry in journal.catalog():
            conversations.append(
                {
                    "thread_id": entry.thread_id,
                    "messages": journal.read_messages(entry.thread_id),
                }
            )
        return {
            "packaged_assets": web_dist.name in {"_web", "dist"},
            "prepare_calls": spine.prepare_calls,
            "commit_calls": spine.commit_calls,
            "receipt_lines": spine.receipt_lines,
            "compactions": spine.compactions,
            "compaction_histories": sum(
                len(thread.compaction_histories) for thread in journal.hydrate_threads()
            ),
            "conversations": conversations,
        }

    app.mount("/", harness_app)
    return app


__all__ = ["ANSWER", "FIXTURE", "PROMPT", "create_scenario_app"]
