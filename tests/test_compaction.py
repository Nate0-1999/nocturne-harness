"""SPEC D.2 101/144/153: the one memory creation event preserves live work."""

import json

import pytest
from pydantic_ai.messages import (
    ModelRequest, ModelResponse, TextPart, ToolReturnPart, UserPromptPart,
)
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from harness.agent import HarnessAgent
from harness.agent_runtime import PydanticAITurnRunner
from harness.extraction import ExtractionService
from harness.model_policy import ThreadModelResolution
from harness.spine_client import ExtractionResponse
from harness.transcript import TranscriptJournal
from tests.test_agent_runtime import RecordingEmitter, context, settings


@pytest.mark.asyncio
async def test_real_runner_compacts_once_and_keeps_resumable_history(tmp_path):
    """D.2 153: old content exits once through triage, without losing the next response."""
    summaries = []
    requests = []

    def summarize(messages, info):
        summaries.append(messages)
        return ModelResponse(parts=[TextPart(json.dumps({
            "working_summary": "## Intent\nFinish the copper notebook.",
            "open_loops": ["Check the final page."], "candidates": [],
        }))])

    async def answer(messages, info):
        requests.append(messages)
        yield "The final page is checked."

    class Palace:
        async def notify_compaction(self, event_uid, thread_id):
            pass

        async def create_extraction(self, request):
            return ExtractionResponse(cards=[], duplicate_count=0)

    model = FunctionModel(function=summarize, stream_function=answer)
    agent = HarnessAgent(settings(), model=model)
    deps = context()
    journal = TranscriptJournal(tmp_path / "journal")
    journal.append_thread_context(str(deps.thread_id), "project-1")
    service = ExtractionService(journal=journal, agent=agent, spine=Palace(),
                                principal_id="principal-1", machine_id="machine-1")
    runner = PydanticAITurnRunner(agent, lambda _: deps, extraction=service)
    history = tuple(message for i in range(12) for message in (
        ModelRequest([UserPromptPart(f"Page {i}: " + "old detail " * 100)]),
        ModelResponse([TextPart("Page checked.")]),
    ))
    emit = RecordingEmitter()
    outcome = await runner.run(thread_id=str(deps.thread_id), prompt="Check the final page.",
        message_history=history, emit=emit,
        model_resolution=ThreadModelResolution(model=settings().chat_model,
                                               context_tokens=2000, policy="pinned"))
    assert outcome.stop_reason.value == "end_turn", outcome.error_message
    assert len(summaries) == 1
    assert len(outcome.message_history) < len(history)
    assert outcome.assistant_text == "The final page is checked."
    assert any(e["event_kind"] == "compaction_completed" for e in emit.events)
    assert "Finish the copper notebook" in str(requests[0])
    restored = journal.hydrate_threads()[0]
    assert emit.run_id in restored.compaction_histories


@pytest.mark.asyncio
async def test_large_worker_return_is_journaled_capped_and_cannot_trigger_compaction(tmp_path):
    """D.2 153: the actual delegated run has no memory tools and bulk never forces compaction."""
    full_return = "worker evidence " * 6000
    parent_returns = []

    def worker(messages, info):
        assert not {"save_memory", "search_memory", "edit_memory"} & {
            tool.name for tool in info.function_tools
        }
        return ModelResponse([TextPart(full_return)])

    async def parent(messages, info):
        returned = [part for message in messages if isinstance(message, ModelRequest)
                    for part in message.parts if isinstance(part, ToolReturnPart)]
        if returned:
            parent_returns.extend(returned)
            yield "The worker result is recorded."
        else:
            yield {0: DeltaToolCall(name="delegate_task", json_args='{"task":"Report evidence"}',
                                   tool_call_id="worker-call")}

    model = FunctionModel(function=worker, stream_function=parent)
    agent = HarnessAgent(settings(), model=model)
    deps = context()
    journal = TranscriptJournal(tmp_path / "journal")
    journal.append_thread_context(str(deps.thread_id), "project-1")
    service = ExtractionService(journal=journal, agent=agent, spine=object(),
                                principal_id="principal-1", machine_id="machine-1")
    runner = PydanticAITurnRunner(agent, lambda _: deps, extraction=service)
    emit = RecordingEmitter()
    outcome = await runner.run(thread_id=str(deps.thread_id), prompt="Delegate the evidence.",
        message_history=(), emit=emit,
        model_resolution=ThreadModelResolution(model=settings().chat_model,
                                               context_tokens=2000, policy="pinned"))
    assert outcome.stop_reason.value == "end_turn", outcome.error_message
    assert len(parent_returns) == 1
    assert len(parent_returns[0].content.encode()) <= 64 * 1024
    assert "Return capped" in parent_returns[0].content
    assert not any(event["event_kind"].startswith("compaction") for event in emit.events)
    rows = [json.loads(line) for line in journal.path_for_thread(str(deps.thread_id)).read_text().splitlines()]
    saved = next(row for row in rows if row["record_type"] == "worker_return")
    assert saved["result"] == full_return
