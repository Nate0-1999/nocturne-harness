"""SPEC D.2 101/144/153: the one memory creation event preserves live work."""

import json
from dataclasses import replace

import pytest
from pydantic_ai.capabilities import Capability
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.tools import Tool
from pydantic_ai_harness.compaction import pin
from spine.tokens import cl100k_token_count

from harness.agent import HarnessAgent
from harness.agent_runtime import PydanticAITurnRunner, _configure_compaction
from harness.context_window import (
    OverwhelmTracker,
    cut_notice,
    send_back_instruction,
    shorten_by,
)
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


def _delegating_parent(parent_returns, json_args='{"task":"Report evidence"}'):
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
                    name="delegate_task", json_args=json_args, tool_call_id="worker-call"
                )
            }

    return parent


async def _delegate_turn(tmp_path, model, *, context_tokens=2000):
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
    tracker = OverwhelmTracker(agent.return_share_bounds)
    runner = PydanticAITurnRunner(agent, lambda _: deps, extraction=service, overwhelm=tracker)
    emit = RecordingEmitter()
    outcome = await runner.run(
        thread_id=str(deps.thread_id),
        prompt="Delegate the evidence.",
        message_history=(),
        emit=emit,
        model_resolution=ThreadModelResolution(
            model=settings().chat_model, context_tokens=context_tokens, policy="pinned"
        ),
    )
    assert outcome.stop_reason.value == "end_turn", outcome.error_message
    rows = [
        json.loads(line)
        for line in journal.path_for_thread(str(deps.thread_id)).read_text().splitlines()
    ]
    return emit, rows, tracker.snapshot(str(deps.thread_id))


def _last_prompt(messages):
    return next(
        part.content
        for message in reversed(messages)
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    )


@pytest.mark.asyncio
async def test_large_worker_return_is_sent_back_twice_then_cut_with_a_head(tmp_path):
    """SPEC D.2 153 / FL-198: a return over its share is told the exact shorten-by, twice,
    then delivered as an error with a brief head; every full return stays in the journal."""
    full_return = "worker evidence " * 6000
    parent_returns = []
    worker_prompts = []

    def worker(messages, info):
        assert not {"save_memory", "search_memory", "edit_memory"} & {
            tool.name for tool in info.function_tools
        }
        worker_prompts.append(_last_prompt(messages))
        return ModelResponse([TextPart(full_return)])

    model = FunctionModel(function=worker, stream_function=_delegating_parent(parent_returns))
    emit, rows, snapshot = await _delegate_turn(tmp_path, model)

    share = snapshot.shares[snapshot.selected_thread_id]
    assert (share.percent, share.limit_tokens, share.tokens) == (10.0, 1600, 160)
    size = cl100k_token_count(full_return)
    expected_d = shorten_by(size, share, thread_id="t", agent_id="a")
    assert expected_d == size - 160 + cl100k_token_count(
        cut_notice(snapshot.cuts[-1], "", journaled=True)
    )
    assert [cut.action for cut in snapshot.cuts] == ["send_back", "send_back", "cut"]
    assert [cut.shorten_by for cut in snapshot.cuts] == [expected_d, expected_d, None]
    assert len(worker_prompts) == 3
    assert worker_prompts[1] == worker_prompts[2] == send_back_instruction(snapshot.cuts[0])
    assert f"shortened by exactly {expected_d:,} tokens" in worker_prompts[1]

    assert len(parent_returns) == 1
    delivered = parent_returns[0].content
    assert delivered.startswith(
        f"Not delivered: this sub-agent return is {size:,} tokens; its share is 160 tokens "
        "(10% of the 1,600-token compaction limit). The full text is in the conversation "
        "journal.\nHead:\n"
    )
    assert delivered.endswith("[... page text truncated at 240 characters]")
    assert cl100k_token_count(delivered) < 160
    assert not any(event["event_kind"].startswith("compaction") for event in emit.events)
    worker_event = next(event for event in emit.events if event["event_kind"] == "worker_return")
    assert (worker_event["capped"], worker_event["send_backs"]) == (True, 2)
    assert [event["action"] for event in emit.events if event["event_kind"] == "context_cut"] == [
        "send_back",
        "send_back",
        "cut",
    ]
    assert [row["result"] for row in rows if row["record_type"] == "worker_return"] == [
        full_return
    ] * 3
    cuts = [row for row in rows if row["record_type"] == "return_cut"]
    assert [row["cut"]["action"] for row in cuts] == ["send_back", "send_back", "cut"]
    assert all(row["result"] == full_return for row in cuts)


@pytest.mark.asyncio
async def test_worker_that_shortens_on_request_is_delivered_whole(tmp_path):
    """SPEC D.2 153 / FL-198: one send-back, a compliant return under the share, delivered
    untouched — worker bulk never forces the main thread to compact."""
    full_return = "worker evidence " * 6000
    parent_returns = []

    def worker(messages, info):
        if _last_prompt(messages).startswith("Your return is"):
            return ModelResponse([TextPart("Short evidence.")])
        return ModelResponse([TextPart(full_return)])

    model = FunctionModel(function=worker, stream_function=_delegating_parent(parent_returns))
    emit, rows, snapshot = await _delegate_turn(tmp_path, model)

    assert parent_returns[0].content == "Short evidence."
    assert [cut.action for cut in snapshot.cuts] == ["send_back"]
    worker_event = next(event for event in emit.events if event["event_kind"] == "worker_return")
    assert (worker_event["capped"], worker_event["send_backs"]) == (False, 1)
    assert [row["result"] for row in rows if row["record_type"] == "worker_return"] == [
        full_return,
        "Short evidence.",
    ]


@pytest.mark.asyncio
async def test_sender_picks_a_share_inside_the_system_bounds(tmp_path):
    """SPEC D.2 153 / FL-198: the delegating agent chooses the share per call and the
    system bounds clamp it, so no sender can exceed the compaction protection."""
    parent_returns = []

    def worker(messages, info):
        return ModelResponse([TextPart("worker evidence " * 6000)])

    model = FunctionModel(
        function=worker,
        stream_function=_delegating_parent(
            parent_returns, json_args='{"task":"Report evidence","share_percent":90}'
        ),
    )
    _, _, snapshot = await _delegate_turn(tmp_path, model)
    assert snapshot.bounds.max_percent == 25.0
    assert {(cut.share.percent, cut.share.tokens) for cut in snapshot.cuts} == {(25.0, 400)}


@pytest.mark.asyncio
async def test_query_result_over_its_share_is_refused_with_a_brief_head():
    """SPEC D.2 153 / FL-198: a tool result over the share is not delivered; the agent gets
    the error and the library's head, and the full text goes to the journal through record_cut."""
    seen = []

    def model(messages, info):
        returned = [
            part
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if returned:
            seen.extend(returned)
            return ModelResponse([TextPart("done")])
        return ModelResponse([ToolCallPart(tool_name="probe", args={}, tool_call_id="c1")])

    def probe() -> str:
        return "page text " * 2000

    recorded = []

    async def record(cut, text):
        recorded.append((cut, text))

    share = HarnessAgent(settings()).return_share_bounds.share(1600)
    deps = replace(context(), return_share=share, record_cut=record)
    agent = HarnessAgent(settings(), model=FunctionModel(function=model))
    await agent.chat_agent.run(
        "go", deps=deps, capabilities=[Capability(id="probe", tools=[Tool(probe)])]
    )
    assert seen[0].content == cut_notice(recorded[0][0], "page text " * 2000, journaled=True)
    assert seen[0].content.startswith(
        "Not delivered: this result is 4,001 tokens; its share is 160 tokens "
        "(10% of the 1,600-token compaction limit). The full text is in the conversation "
        "journal.\nHead:\npage text page text"
    )
    assert seen[0].content.endswith("[... page text truncated at 240 characters]")
    assert (recorded[0][0].kind, recorded[0][0].source, recorded[0][1]) == (
        "query",
        "probe",
        "page text " * 2000,
    )


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
