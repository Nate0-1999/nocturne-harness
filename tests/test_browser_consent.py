from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from harness.agent import HarnessAgent
from harness.agent_runtime import PydanticAITurnRunner
from harness.config import HarnessSettings
from harness.envelope import StopReason
from harness.memory_gate import MemoryGateTurnRunner
from harness.run_protocol import UsageSnapshot
from harness.tools_memory import MemoryToolContext
from harness.toolset import AgentLocation

THREAD_ID = "33333333-3333-4333-8333-333333333333"


@dataclass
class ConsentToolset:
    grants: list[str] = field(default_factory=list)

    def grant_open_web(self, thread_id: str) -> None:
        self.grants.append(thread_id)

    def location(self) -> AgentLocation:
        path = Path.cwd()
        return AgentLocation("agent", "machine", "session", path, path, False)


@dataclass
class Emitter:
    text_values: list[str] = field(default_factory=list)

    async def text(self, value: str) -> None:
        self.text_values.append(value)

    async def thinking(self, value: str) -> None:
        del value

    async def event(self, value: object) -> None:
        del value

    async def usage(self, value: UsageSnapshot) -> None:
        del value

    async def gate(self, value: object) -> object:
        raise AssertionError(f"consent command must not open memory gate: {value}")

    async def error(self, value: object) -> None:
        raise AssertionError(f"consent command must not emit an error: {value}")


@pytest.mark.asyncio
async def test_open_web_command_bypasses_model_and_first_turn_memory_gate() -> None:
    async def model_must_not_run(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        raise AssertionError(f"consent command reached model: {messages!r} {info!r}")

    toolset = ConsentToolset()

    def context_factory(thread_id: str) -> MemoryToolContext:
        return MemoryToolContext(
            spine=object(),  # type: ignore[arg-type]
            principal_id="owner",
            machine_id="machine",
            agent_id="agent",
            thread_id=UUID(thread_id),
            origin_path="/workspace",
            toolset=toolset,  # type: ignore[arg-type]
        )

    agent = HarnessAgent(
        HarnessSettings(),
        model=FunctionModel(model_must_not_run, model_name="consent-tripwire"),
    )
    runner = MemoryGateTurnRunner(
        PydanticAITurnRunner(agent, context_factory),
        object(),  # type: ignore[arg-type]
        context_factory,
        model_context_tokens=100_000,
    )
    emitter = Emitter()

    outcome = await runner.run(
        thread_id=THREAD_ID,
        prompt="/browser allow-web",
        message_history=(),
        emit=emitter,  # type: ignore[arg-type]
    )

    assert outcome.stop_reason is StopReason.END_TURN
    assert outcome.model_visible is False
    assert outcome.usage == UsageSnapshot()
    assert toolset.grants == [THREAD_ID]
    assert emitter.text_values == ["Open-web browser access is allowed for this thread."]
