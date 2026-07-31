from __future__ import annotations

import json
from pathlib import Path

TRACE = Path(__file__).with_name("wire-and-daemon.jsonl")
J1_THREAD = "fb3f7b5f-3fe9-4948-b998-6a30b8f53ff4"
J2_THREAD = "f72c7b55-6c53-476d-b7b1-b97a4ec29760"
DEFAULT_MODEL = "openrouter:minimax/minimax-m3"
NEW_MODEL = "openrouter:x-ai/grok-4.5"
MEMORY_ID = "c358ab87-4d96-4696-a82d-02cfb5683121"


def wire(records: list[dict[str, object]], thread_id: str) -> list[dict[str, object]]:
    return [
        record
        for record in records
        if record.get("kind") == "wire.envelope"
        and record["envelope"].get("thread_id") == thread_id
    ]


def main() -> None:
    records = [json.loads(line) for line in TRACE.read_text().splitlines()]
    assert [record["sequence"] for record in records] == list(range(1, len(records) + 1))

    wire_records = [record for record in records if record.get("kind") == "wire.envelope"]
    envelope_ids = [record["envelope"]["id"] for record in wire_records]
    assert len(envelope_ids) == len(set(envelope_ids))
    required_outer = {"v", "id", "ts", "machine_id", "type", "payload"}
    for record in wire_records:
        envelope = record["envelope"]
        assert required_outer <= envelope.keys()
        assert envelope["v"] == 1
        if envelope["type"] == "run.delta":
            payload = envelope["payload"]
            assert payload["kind"] in {"text", "thinking", "event"}
            assert "run_id" in payload
            if payload["kind"] == "event":
                assert isinstance(payload["event"], dict)
            else:
                assert isinstance(payload["text"], str)

    started = records[0]
    assert started["kind"] == "scenario.started"
    assert started["harness_commit"] == "66f1cc1199e29fffae1d4fe6e94253ab6d5b37c8"
    assert started["spine_commit"] == "7febef353783c981fb68055e00904fa33c98856c"

    j1 = wire(records, J1_THREAD)
    j1_submits = [
        record["envelope"]["payload"]["prompt"]
        for record in j1
        if record["envelope"]["type"] == "prompt.submit"
    ]
    assert j1_submits == [
        "hello",
        f"/model {NEW_MODEL}",
        "Reply exactly: post-switch exchange complete.",
    ]

    j1_starts = [
        record["envelope"]["payload"]
        for record in j1
        if record["envelope"]["type"] == "run.started"
    ]
    assert [payload["resolved_model"] for payload in j1_starts] == [
        DEFAULT_MODEL,
        DEFAULT_MODEL,
        NEW_MODEL,
    ]

    changes = [
        record["envelope"]["payload"]
        for record in j1
        if record["envelope"]["type"] == "run.delta"
        and record["envelope"]["payload"].get("event", {}).get("event_kind") == "model_change"
    ]
    assert len(changes) == 1
    change = changes[0]
    assert change["resolved_model"] == NEW_MODEL
    assert change["event"] == {
        "event_kind": "model_change",
        "old_model": DEFAULT_MODEL,
        "new_model": NEW_MODEL,
        "reason": "human_command",
        "timestamp": "2026-07-31T17:04:00.610255+00:00",
        "stickiness_epoch": 1,
        "sacrificed_cached_prefix_tokens": 956,
        "context_tokens": 500000,
    }

    command_run = j1_starts[1]["run_id"]
    command_usage = [
        record["envelope"]["payload"]
        for record in j1
        if record["envelope"]["type"] == "run.usage"
        and record["envelope"]["payload"]["run_id"] == command_run
    ]
    assert command_usage == [
        {"requests": 0, "input_tokens": 0, "output_tokens": 0, "run_id": command_run}
    ]

    post_run = j1_starts[2]["run_id"]
    post_text = "".join(
        record["envelope"]["payload"].get("text", "")
        for record in j1
        if record["envelope"]["type"] == "run.delta"
        and record["envelope"]["payload"]["run_id"] == post_run
        and record["envelope"]["payload"]["kind"] == "text"
    )
    assert post_text == "post-switch exchange complete."
    assert any(
        record["envelope"]["type"] == "run.done"
        and record["envelope"]["payload"]
        == {"run_id": post_run, "stop_reason": "end_turn", "partial": False}
        for record in j1
    )
    snapshots = [
        record["envelope"]["payload"]
        for record in j1
        if record["direction"] == "daemon_to_client"
        and record["envelope"]["type"] == "thread.snapshot"
        and record["envelope"]["payload"].get("messages")
    ]
    assert snapshots
    assert all(snapshot["resolved_model"] == NEW_MODEL for snapshot in snapshots)
    assert all(len(snapshot["messages"]) == 6 for snapshot in snapshots)

    j2 = wire(records, J2_THREAD)
    j2_starts = [
        record["envelope"]["payload"]
        for record in j2
        if record["envelope"]["type"] == "run.started"
    ]
    assert len(j2_starts) == 2
    assert all(payload["resolved_model"] == DEFAULT_MODEL for payload in j2_starts)

    tool_calls = [
        record["envelope"]["payload"]
        for record in j2
        if record["envelope"]["type"] == "run.delta"
        and record["envelope"]["payload"].get("event", {}).get("event_kind") == "function_tool_call"
    ]
    assert len(tool_calls) == 2
    assert {payload["run_id"] for payload in tool_calls} == {
        payload["run_id"] for payload in j2_starts
    }
    parsed_args = []
    for payload in tool_calls:
        part = payload["event"]["part"]
        assert part["tool_name"] == "save_memory"
        assert payload["event"]["args_valid"] is True
        args = json.loads(part["args"])
        assert args["force"] is False
        assert args["project_scoped"] is False
        parsed_args.append(args)
    assert [args["label"] for args in parsed_args] == [
        "Code indentation preference",
        "Tabs for indentation",
    ]
    assert [args["body"] for args in parsed_args] == [
        "I prefer tabs over spaces for code indentation.",
        "For code indentation, tabs are my preference instead of spaces.",
    ]

    all_tool_names = {
        event["part"]["tool_name"]
        for record in j2
        if record["envelope"]["type"] == "run.delta"
        for event in [record["envelope"]["payload"].get("event", {})]
        if isinstance(event.get("part"), dict) and event["part"].get("tool_name")
    }
    assert all_tool_names == {"save_memory"}

    create_calls = [record for record in records if record.get("kind") == "spine.create.call"]
    assert len(create_calls) == 2
    assert [record["attempt"] for record in create_calls] == [1, 2]
    assert all(record["force"] is False for record in create_calls)
    create_results = [record for record in records if record.get("kind") == "spine.create.result"]
    assert create_results[0]["status_code"] == 201
    assert create_results[0]["outcome"] == "created"
    assert create_results[0]["memory"]["memory_id"] == MEMORY_ID
    assert create_results[1]["status_code"] == 200
    assert create_results[1]["outcome"] == "similar"
    assert create_results[1]["similar"][0]["memory_id"] == MEMORY_ID
    assert create_results[1]["similar"][0]["score"] == 0.9075139432499054

    cleaned = records[-1]
    assert cleaned == {
        "sequence": len(records),
        "at": cleaned["at"],
        "kind": "scenario.cleaned",
        "memory_id": MEMORY_ID,
        "final_revision": 2,
        "final_status": "tombstoned",
        "remaining_active_ids": [],
    }
    print("I1 v2.26 J1/J2 trace audit: PASS")


if __name__ == "__main__":
    main()
