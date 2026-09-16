"""SPEC D.2 101/144/153: the one memory creation event preserves live work."""

import json

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai_harness.compaction import pin

from harness.agent import HarnessAgent
from harness.agent_runtime import PydanticAITurnRunner, _configure_compaction
from harness.extraction import ExtractionService
from harness.model_policy import ThreadModelResolution
from harness.pydantic_harness_adapter import CompactionPolicy
from harness.spine_client import ExtractionResponse
from harness.transcript import TranscriptJournal
from tests.test_agent_runtime import RecordingEmitter, context, settings


@pytest.mark.asyncio
@pytest.mark.parametrize("corrected", [True, False])
async def test_over_cap_fact_is_shortened_once_or_refused(corrected):
    """SPEC D.2 / SD-062: shorten one fact atomically; failed shortening prevents admission."""
    calls = []
    receipts = []

    def extract(messages, info):
        calls.append(messages)
        assert info.model_settings["temperature"] == 0
        assert info.model_settings["openrouter_usage"] == {"include": True}
        body = "The notebook is copper." if corrected and len(calls) == 2 else "copper " * 200
        return ModelResponse(
            [
                TextPart(
                    json.dumps(
                        {
                            "working_summary": "Finish the notebook.",
                            "open_loops": [],
                            "candidates": [
                                {
                                    "label": "Notebook",
                                    "body": body,
                                    "kind": "fact",
                                    "keywords": ["notebook", "copper"],
                                }
                            ],
                        }
                    )
                )
            ]
        )

    async def receipt(messages):
        receipts.append(messages)

    agent = HarnessAgent(settings(), model=FunctionModel(function=extract))
    if corrected:
        draft = await agent.extract_thread("One notebook fact.", on_result=receipt)
        assert len(draft.candidates) == 1
        assert draft.candidates[0].body == "The notebook is copper."
    else:
        with pytest.raises(
            ValueError,
            match="Compaction could not preserve a fact within the memory cap; history kept.",
        ):
            await agent.extract_thread("One notebook fact.", on_result=receipt)
    assert len(calls) == len(receipts) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "strategy", ["truncate", "summarize", "memories-then-drop", "human-and-final-only"]
)
async def test_real_runner_compacts_once_and_keeps_resumable_history(tmp_path, strategy):
    """SPEC D.2 153: triage removes old content without losing the next response."""
    summaries = []
    requests = []

    def summarize(messages, info):
        summaries.append(messages)
        return ModelResponse(
            parts=[
                TextPart(
                    json.dumps(
                        {
                            "working_summary": "## Intent\nFinish the copper notebook.",
                            "open_loops": ["Check the final page."],
                            "candidates": [],
                        }
                    )
                )
            ]
        )

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
    journal.append_compaction_policy(
        str(deps.thread_id), CompactionPolicy(strategy=strategy).model_dump()
    )
    service = ExtractionService(
        journal=journal,
        agent=agent,
        spine=Palace(),
        principal_id="principal-1",
        machine_id="machine-1",
    )
    runner = PydanticAITurnRunner(agent, lambda _: deps, extraction=service)
    history = (
        ModelRequest([pin("Pinned task: finish the notebook.")]),
        *tuple(
            message
            for i in range(12)
            for message in (
                ModelRequest([UserPromptPart(f"Page {i}: " + "old detail " * 100)]),
                ModelResponse([TextPart("Page checked.")]),
            )
        ),
    )
    emit = RecordingEmitter()
    outcome = await runner.run(
        thread_id=str(deps.thread_id),
        prompt="Check the final page.",
        message_history=history,
        emit=emit,
        model_resolution=ThreadModelResolution(
            model=settings().chat_model, context_tokens=2000, policy="pinned"
        ),
    )
    assert outcome.stop_reason.value == "end_turn", outcome.error_message
    assert len(summaries) == 1
    assert len(outcome.message_history) < len(history)
    assert outcome.assistant_text == "The final page is checked."
    assert any(e["event_kind"] == "compaction_completed" for e in emit.events)
    assert ("Finish the copper notebook" in str(requests[0])) == (strategy == "summarize")
    assert ("Page 0:" in str(requests[0])) == (
        strategy in {"memories-then-drop", "human-and-final-only"}
    )
    assert "Pinned task: finish the notebook." in str(requests[0])
    assert "History before this point" in str(requests[0])
    restored = journal.hydrate_threads()[0]
    assert emit.run_id in restored.compaction_histories


@pytest.mark.asyncio
async def test_large_worker_return_is_journaled_capped_and_cannot_trigger_compaction(tmp_path):
    """SPEC D.2 153: workers have no memory tools and bulk never forces compaction."""
    full_return = "worker evidence " * 6000
    parent_returns = []

    def worker(messages, info):
        assert not {"save_memory", "search_memory", "edit_memory"} & {
            tool.name for tool in info.function_tools
        }
        return ModelResponse([TextPart(full_return)])

    async def parent(messages, info):
        returned = [
            part
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if returned:
            parent_returns.extend(returned)
            yield "The worker result is recorded."
        else:
            yield {
                0: DeltaToolCall(
                    name="delegate_task",
                    json_args='{"task":"Report evidence"}',
                    tool_call_id="worker-call",
                )
            }

    model = FunctionModel(function=worker, stream_function=parent)
    agent = HarnessAgent(settings(), model=model)
    deps = context()
    journal = TranscriptJournal(tmp_path / "journal")
    journal.append_thread_context(str(deps.thread_id), "project-1")
    service = ExtractionService(
        journal=journal,
        agent=agent,
        spine=object(),
        principal_id="principal-1",
        machine_id="machine-1",
    )
    runner = PydanticAITurnRunner(agent, lambda _: deps, extraction=service)
    emit = RecordingEmitter()
    outcome = await runner.run(
        thread_id=str(deps.thread_id),
        prompt="Delegate the evidence.",
        message_history=(),
        emit=emit,
        model_resolution=ThreadModelResolution(
            model=settings().chat_model, context_tokens=2000, policy="pinned"
        ),
    )
    assert outcome.stop_reason.value == "end_turn", outcome.error_message
    assert len(parent_returns) == 1
    assert len(parent_returns[0].content.encode()) <= 64 * 1024
    assert "Return capped" in parent_returns[0].content
    assert not any(event["event_kind"].startswith("compaction") for event in emit.events)
    rows = [
        json.loads(line)
        for line in journal.path_for_thread(str(deps.thread_id)).read_text().splitlines()
    ]
    saved = next(row for row in rows if row["record_type"] == "worker_return")
    assert saved["result"] == full_return


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_admission", [False, True])
async def test_failure_keeps_the_correct_history_before_or_after_admission(
    tmp_path, fail_admission
):
    """SPEC D.2 101: queue failure keeps history; later failure retains admitted compaction."""

    def extract(messages, info):
        return ModelResponse(
            [
                TextPart(
                    json.dumps(
                        {
                            "working_summary": "The notebook is nearly done.",
                            "open_loops": [],
                            "candidates": [],
                        }
                    )
                )
            ]
        )

    async def fail(messages, info):
        yield "The partial answer."
        raise RuntimeError("provider stopped")

    class Palace:
        async def create_extraction(self, request):
            if fail_admission:
                raise RuntimeError("queue unavailable")
            return ExtractionResponse(cards=[], duplicate_count=0)

        async def notify_compaction(self, event_uid, thread_id):
            pass

    model = FunctionModel(function=extract, stream_function=fail)
    agent = HarnessAgent(settings(), model=model)
    deps = context()
    journal = TranscriptJournal(tmp_path / "journal")
    journal.append_thread_context(str(deps.thread_id), "project-1")
    service = ExtractionService(
        journal=journal,
        agent=agent,
        spine=Palace(),
        principal_id="principal-1",
        machine_id="machine-1",
    )
    runner = PydanticAITurnRunner(agent, lambda _: deps, extraction=service)
    history = tuple(
        message
        for i in range(8)
        for message in (
            ModelRequest([UserPromptPart(f"Page {i}")]),
            ModelResponse([TextPart("old details " * 200)]),
        )
    )
    emit = RecordingEmitter()
    outcome = await runner.run(
        thread_id=str(deps.thread_id),
        prompt="Continue.",
        message_history=history,
        emit=emit,
        model_resolution=ThreadModelResolution(
            model=settings().chat_model, context_tokens=1000, policy="pinned"
        ),
    )
    assert outcome.stop_reason.value == "error"
    checkpoint = journal.hydrate_threads()[0].compaction_histories.get(emit.run_id)
    if fail_admission:
        assert checkpoint is None
        assert all(message in outcome.message_history for message in history)
        assert "Continue." in str(outcome.message_history)
    else:
        assert checkpoint is not None
        assert len(outcome.message_history) < len(history)
        assert "History before this point" in str(outcome.message_history)


@pytest.mark.asyncio
async def test_policy_commands_survive_restart_and_manual_compaction_bypasses_fill(tmp_path):
    """SPEC D.2 153: manual controls are per-thread durable and work below the automatic line."""

    with pytest.raises(ValueError, match="Unknown compaction control"):
        _configure_compaction(CompactionPolicy(), "unsupported setting")

    def extract(messages, info):
        return ModelResponse(
            [
                TextPart(
                    json.dumps(
                        {
                            "working_summary": "Continue the notebook.",
                            "open_loops": [],
                            "candidates": [],
                        }
                    )
                )
            ]
        )

    class Palace:
        async def create_extraction(self, request):
            return ExtractionResponse(cards=[], duplicate_count=0)

        async def notify_compaction(self, event_uid, thread_id):
            pass

    agent = HarnessAgent(settings(), model=FunctionModel(function=extract))
    deps = context()
    journal = TranscriptJournal(tmp_path / "journal")
    journal.append_thread_context(str(deps.thread_id), "project-1")
    service = ExtractionService(
        journal=journal,
        agent=agent,
        spine=Palace(),
        principal_id="principal-1",
        machine_id="machine-1",
    )
    for command in ("/compact policy cost 0.45", "/compact strategy human-and-final-only"):
        runner = PydanticAITurnRunner(agent, lambda _: deps, extraction=service)
        outcome = await runner.run(
            thread_id=str(deps.thread_id),
            prompt=command,
            message_history=(),
            emit=RecordingEmitter(),
        )
        assert outcome.stop_reason.value == "end_turn"
        assert outcome.model_visible is False
    restored = TranscriptJournal(tmp_path / "journal").compaction_policy(str(deps.thread_id))
    assert restored["policy"] == "cost"
    assert restored["fraction"] == 0.45
    assert restored["strategy"] == "human-and-final-only"
    history = (
        ModelRequest([UserPromptPart("First")]),
        ModelResponse([TextPart("Old answer")]),
        ModelRequest([UserPromptPart("Second")]),
        ModelResponse([TextPart("Final answer")]),
    )
    outcome = await runner.run(
        thread_id=str(deps.thread_id),
        prompt="/compact",
        message_history=history,
        emit=RecordingEmitter(),
    )
    assert outcome.stop_reason.value == "end_turn", outcome.error_message
    assert "Old answer" not in str(outcome.message_history)
    assert "Final answer" in str(outcome.message_history)
    repeated = await runner.run(
        thread_id=str(deps.thread_id),
        prompt="/compact",
        message_history=outcome.message_history,
        emit=RecordingEmitter(),
    )
    assert repeated.assistant_text == "No older context to compact yet."
