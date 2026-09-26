from pathlib import Path

import pytest
from fastapi import HTTPException

from harness.visualization import VisualizationHistory, directory_tree, observe_worker


def test_tree_preserves_empty_hidden_and_untracked_entries_without_following_links(tmp_path):
    """FL-126 / ADR-018: chamber truth includes empty folders and every file, not Git alone."""
    (tmp_path / "empty").mkdir()
    (tmp_path / ".hidden").write_text("private content must never enter the feed")
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    tree = directory_tree(tmp_path)
    assert {row["path"]: row["kind"] for row in tree["nodes"]} == {
        ".": "directory",
        ".hidden": "file",
        "empty": "directory",
        "link": "link",
    }
    assert "private content" not in str(tree)
    assert not tree["errors"]


def test_recorded_history_survives_restart_and_replays_deletion_exactly(tmp_path):
    """ADR-018 / FL-134: past observations are immutable, never reconstructed from today's tree."""
    root = tmp_path / "work"
    root.mkdir()
    file = root / "one.txt"
    file.write_text("one")
    path = tmp_path / "history.sqlite3"
    history = VisualizationHistory(path)
    first = {"agents": [], "projects": [directory_tree(root)]}
    history.append(first, "2026-09-16T01:00:00+00:00")
    history.append(first, "2026-09-16T01:00:01+00:00")
    file.unlink()
    history.append({"agents": [], "projects": [directory_tree(root)]}, "2026-09-16T01:00:02+00:00")
    history = VisualizationHistory(path)
    past = history.read("2026-09-16T01:00:00+00:00")
    assert past["projects"] == first["projects"]
    assert past == history.read("2026-09-16T01:00:00+00:00")
    assert len(history.read()["projects"][0]["nodes"]) == 1
    assert len(past["timeline"]) == 2
    with pytest.raises(HTTPException, match="No recorded"):
        history.read("2026-09-15T00:00:00+00:00")


def test_worker_observation_uses_actual_location_without_assignment_secrets(tmp_path):
    """ADR-018 / FL-126/129: ants follow real feet; feeds never serialize private assignments."""
    from types import SimpleNamespace

    assignment = {
        "origin_agent": "run/root.1",
        "thread_id": "thread",
        "project_key": "/work",
        "stage": "completion",
        "env_file": "secret",
        "brief": "private prompt",
    }
    observe_worker(
        tmp_path,
        assignment,
        SimpleNamespace(cwd=Path("/work/src"), workspace_root=Path("/work")),
        "running",
    )
    value = (tmp_path / "visualization.json").read_text()
    assert "/work/src" in value
    assert "private prompt" not in value and "secret" not in value


def test_worker_observation_preserves_start_and_does_not_block_work_on_io_failure(tmp_path):
    """ADR-018 / FL-129: a moving ant keeps its birth time; telemetry is not authority."""
    import json
    from types import SimpleNamespace

    assignment = {
        "origin_agent": "worker",
        "thread_id": "thread",
        "project_key": "/work",
        "stage": "completion",
    }
    location = SimpleNamespace(cwd=Path("/work"), workspace_root=Path("/work"))
    observe_worker(tmp_path, assignment, location, "running")
    path = tmp_path / "visualization.json"
    first = json.loads(path.read_text())
    observe_worker(tmp_path, assignment, location, "running")
    assert json.loads(path.read_text()) == first
    location.cwd = Path("/work/src")
    observe_worker(tmp_path, assignment, location, "stopped")
    assert json.loads(path.read_text())["started_at"] == first["started_at"]
    observe_worker(tmp_path / "missing", assignment, location, "running")


def test_file_capillaries_project_successful_paths_without_contents_or_directory_guesses(tmp_path):
    """ADR-018 / PLAN M3VL: capillaries are evidenced file touches, never directory guesses."""
    import json
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from harness.visualization import _journal_file_touch

    files, pending = {}, {}
    call = {"tool_name": "read", "tool_call_id": "read-1", "args": '{"path":"one.txt"}'}
    _journal_file_touch(
        {"event_kind": "function_tool_call", "part": call}, "/work/src", "1", pending, files
    )
    result = {**call, "part_kind": "tool-return", "content": "read refused: File not found"}
    _journal_file_touch(
        {"event_kind": "function_tool_result", "part": result}, "/elsewhere", "2", pending, files
    )
    assert files == {}
    _journal_file_touch(
        {"event_kind": "function_tool_call", "part": call}, "/work/src", "3", pending, files
    )
    result["content"] = "Private file contents must never enter the feed"
    _journal_file_touch(
        {"event_kind": "function_tool_result", "part": result}, "/elsewhere", "4", pending, files
    )
    assert files == {"/work/src/one.txt": "4"}

    touched = tmp_path / "one.txt"
    touched.write_text("Private contents")
    presence = [
        SimpleNamespace(event="read", path=path, ts=datetime(2026, 9, 16, tzinfo=UTC))
        for path in (touched, tmp_path)
    ]
    observe_worker(
        tmp_path,
        {"origin_agent": "child", "thread_id": "parent", "stage": "completion"},
        SimpleNamespace(cwd=tmp_path, workspace_root=tmp_path),
        "running",
        presence,
    )
    value = json.loads((tmp_path / "visualization.json").read_text())
    assert value["touched_files"] == [{"path": str(touched), "ts": "2026-09-16T00:00:00+00:00"}]
    assert "Private contents" not in json.dumps(value)
    observe_worker(
        tmp_path,
        {"origin_agent": "child", "thread_id": "parent", "stage": "completion"},
        SimpleNamespace(cwd=tmp_path, workspace_root=tmp_path),
        "stopped",
    )
    assert (
        json.loads((tmp_path / "visualization.json").read_text())["touched_files"]
        == value["touched_files"]
    )


def test_root_branches_project_turn_and_tool_call_times_without_content(tmp_path):
    """ADR-018 / F115 (M3VL send-back 1): roots branch at each turn and tool call, no content."""
    import json
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart

    from harness.visualization import work_observation

    first, second = datetime(2026, 9, 24, 1, tzinfo=UTC), datetime(2026, 9, 24, 2, tzinfo=UTC)
    messages = [
        ModelRequest.user_text_prompt("PRIVATE-BRIEF"),
        ModelResponse(parts=[ToolCallPart("read", {"path": "SECRET-FILE"})], timestamp=first),
        ModelResponse(parts=[TextPart("PRIVATE-ANSWER")], timestamp=second),
    ]
    output = tmp_path / "symphonies" / "run" / "worker"
    output.mkdir(parents=True)
    location = SimpleNamespace(cwd=tmp_path, workspace_root=tmp_path)
    assignment = {"origin_agent": "run/root.1", "thread_id": "thread", "stage": "completion"}
    observe_worker(output, assignment, location, "running", (), messages)
    worker = json.loads((output / "visualization.json").read_text())
    assert worker["turns"] == [first.isoformat(), second.isoformat()]
    assert worker["tool_calls"] == [first.isoformat()]

    rows = [
        {"captured_at": "t1", "event": {"type": "run.started"}},
        {
            "captured_at": "t2",
            "event": {
                "type": "run.delta",
                "payload": {
                    "event": {
                        "event_kind": "function_tool_call",
                        "part": {"tool_name": "bash", "args": {"command": "PRIVATE-COMMAND"}},
                    }
                },
            },
        },
        {"captured_at": "t3", "event": {"type": "run.done"}},
    ]
    transcript = tmp_path / "thread.jsonl"
    transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
    entry = SimpleNamespace(
        thread_id="thread",
        workspace_root=str(tmp_path),
        current_location=None,
        proposed_response=None,
        title="Thread",
        created_at="t0",
        updated_at="t3",
    )
    journal = SimpleNamespace(catalog=lambda: [entry], path_for_thread=lambda _id: transcript)
    observed = work_observation(journal, tmp_path, tmp_path)["agents"]
    agents = {agent["id"]: agent for agent in observed}
    assert agents["thread"]["turns"] == ["t1"] and agents["thread"]["tool_calls"] == ["t2"]
    assert agents["run/root.1"]["tool_calls"] == [first.isoformat()]
    feed = json.dumps(agents)
    assert "PRIVATE" not in feed and "SECRET" not in feed
