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


def test_trees_rewalk_only_within_the_walk_budget(tmp_path, monkeypatch):
    """M3HW / FL-166: walking every tree every 2 s held a core; a known tree waits its budget,
    a new root is walked at once, and a root that left is forgotten."""
    from harness import visualization

    clock = {"now": 100.0}
    walks = []

    def walk(root):
        walks.append(root.name)
        clock["now"] += 0.1  # each walk costs 0.1 s
        return {"root": str(root), "nodes": [], "errors": []}

    monkeypatch.setattr(visualization.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(visualization, "directory_tree", walk)
    one, two = str(tmp_path / "one"), str(tmp_path / "two")
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    cache: dict = {}
    visualization._project_trees({one}, cache)
    clock["now"] += 2
    visualization._project_trees({one, two}, cache)
    assert walks == ["one", "two"]
    clock["now"] += 0.1 / visualization._WALK_SHARE - 0.1
    assert [tree["root"] for tree in visualization._project_trees({one}, cache)] == [one]
    assert walks == ["one", "two"] and set(cache["trees"]) == {one}
    clock["now"] += 0.2
    visualization._project_trees({one}, cache)
    assert walks == ["one", "two", "one"]
    (tmp_path / "two").rmdir()  # a removed worktree is no longer a project
    assert visualization._project_trees({one, two}, cache) == [cache["trees"][one]]


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


def test_trees_are_stored_once_then_as_changes_and_replay_exactly(tmp_path):
    """M3HW / FL-134: each changed sample stored whole trees (1 GB in a day); a tree is now
    written once, then as its changed entries, and every past state still replays exactly."""
    import json
    import sqlite3
    import zlib

    root = tmp_path / "work"
    root.mkdir()
    for index in range(20):
        (root / f"f{index}.txt").write_text("x")
    path = tmp_path / "history.sqlite3"
    history = VisualizationHistory(path)
    trees = []
    for second, change in enumerate(
        (lambda: None, lambda: (root / "f1.txt").write_text("longer"), (root / "f2.txt").unlink)
    ):
        change()
        trees.append(directory_tree(root))
        agent = {"id": "a", "location": str(root), "cost_usd": None, "state": "running"}
        history.append(
            {"agents": [agent], "projects": [trees[-1]]}, f"2026-09-30T00:00:0{second}+00:00"
        )
    history.append(
        {"agents": [{**agent, "state": "stopped"}], "projects": [trees[-1]]},
        "2026-09-30T00:00:03+00:00",
    )
    restarted = VisualizationHistory(path)
    for second, tree in enumerate([*trees, trees[-1]]):
        assert restarted.read(f"2026-09-30T00:00:0{second}+00:00")["projects"] == [tree]
    assert restarted.read()["projects"] == [trees[-1]]
    with sqlite3.connect(path) as db:
        stored = db.execute("SELECT base IS NULL, payload FROM tree ORDER BY depth").fetchall()
    assert [keyframe for keyframe, _payload in stored] == [1, 0, 0]
    changed, removed = (json.loads(zlib.decompress(payload)) for _, payload in stored[1:])
    assert "f1.txt" in [node["path"] for node in changed["set"]] and not changed["drop"]
    assert removed["drop"] == ["f2.txt"] and len(removed["set"]) <= 1  # the folder's own size


def test_retention_drops_old_rows_keeps_needed_trees_and_reads_the_old_format(tmp_path):
    """M3HW: the store is bounded by a retention window; a tree a kept row builds on survives,
    and rows written before M3HW (whole trees, no trail) are read until they age out."""
    import json
    import sqlite3
    import zlib
    from datetime import timedelta

    root = tmp_path / "work"
    root.mkdir()
    for index in range(20):
        (root / f"f{index}.txt").write_text("x")
    path = tmp_path / "history.sqlite3"
    old_tree = directory_tree(root)
    legacy = {"agents": [{"id": "a", "location": "/x", "cost_usd": None, "state": "stopped"}]}
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE observation "
            "(ts TEXT PRIMARY KEY, digest TEXT NOT NULL, payload BLOB NOT NULL)"
        )
        for ts in ("2026-09-28T00:00:00+00:00", "2026-09-29T23:00:00+00:00"):
            payload = zlib.compress(json.dumps({**legacy, "projects": [old_tree]}).encode())
            db.execute("INSERT INTO observation VALUES (?, ?, ?)", (ts, ts, payload))
    history = VisualizationHistory(path, retention=timedelta(hours=24))
    assert history.read()["projects"] == [old_tree]
    assert history.read()["trails"]["a"][0]["state"] == "stopped"
    running = {"id": "a", "location": "/x", "cost_usd": None, "state": "running"}
    first = directory_tree(root)
    history.append({"agents": [running], "projects": [first]}, "2026-09-30T00:00:00+00:00")
    assert history.read()["timeline"] == ["2026-09-29T23:00:00+00:00", "2026-09-30T00:00:00+00:00"]
    (root / "f1.txt").write_text("longer")
    second = directory_tree(root)
    history.append({"agents": [running], "projects": [second]}, "2026-10-01T01:00:00+00:00")
    assert history.read()["timeline"] == ["2026-10-01T01:00:00+00:00"]
    assert history.read()["projects"] == [second]
    assert VisualizationHistory(path).read("2026-10-01T01:00:00+00:00")["projects"] == [second]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM tree").fetchone() == (2,)  # the base stays
        assert db.execute("PRAGMA auto_vacuum").fetchone() == (2,)


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


def test_samples_read_only_what_the_journal_appended(tmp_path):
    """M3EX-37 / P2.1: the 2 s sampler re-parsed every journal file each time and held gigabytes;
    unchanged files are not read again and a growing file is read from where it stopped."""
    import json

    from harness.transcript import TranscriptJournal
    from harness.visualization import work_observation

    journal = TranscriptJournal(tmp_path / "transcripts")
    thread_id = "00000000-0000-0000-0000-000000003701"
    journal.append_thread_context(
        thread_id, str(tmp_path), workspace_root=str(tmp_path), current_location=str(tmp_path)
    )
    journal.append_message(
        thread_id,
        {
            "message_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "role": "user",
            "content": "first",
            "state": "complete",
        },
        parent_id=None,
    )
    reads = []
    original = journal._read_file_rows
    journal._read_file_rows = lambda filename: reads.append(filename) or original(filename)
    folds: dict = {}
    first = work_observation(journal, tmp_path, tmp_path, folds)["agents"][0]
    assert first["state"] == "stopped" and len(reads) == 1
    offset = folds[thread_id]["offset"]
    work_observation(journal, tmp_path, tmp_path, folds)
    assert len(reads) == 1 and folds[thread_id]["offset"] == offset
    journal._append(
        thread_id,
        {"version": 1, "record_type": "event", "event": {"type": "run.started", "payload": {}}},
    )
    grown = work_observation(journal, tmp_path, tmp_path, folds)["agents"][0]
    assert grown["state"] == "running" and len(grown["turns"]) == 1 and len(reads) == 2
    assert folds[thread_id]["offset"] == journal.path_for_thread(thread_id).stat().st_size
    assert json.dumps(grown) == json.dumps(
        work_observation(journal, tmp_path, tmp_path)["agents"][0]
    )


def test_live_history_reads_fold_only_new_rows(tmp_path):
    """M3EX-37 / P2.1: a live poll decompressed every recorded observation; it now folds new rows
    and returns what a full read returns."""
    path = tmp_path / "history.sqlite3"
    history = VisualizationHistory(path)
    for index, state in enumerate(("running", "running", "stopped")):
        history.append(
            {
                "agents": [{"id": "a", "location": "/x", "cost_usd": index, "state": state}],
                "projects": [],
                "errors": [],
            },
            f"2026-09-28T00:00:0{index}+00:00",
        )
        live = history.read()
        assert live == {**VisualizationHistory(path).read(), "live": True}
    assert live["timeline"] == [f"2026-09-28T00:00:0{index}+00:00" for index in range(3)]
    assert [point["state"] for point in live["trails"]["a"]] == ["running", "running", "stopped"]
    live["errors"].append("caller note")
    assert history.read()["errors"] == []


def test_a_held_tree_is_not_sent_again(tmp_path):
    """M3HW / FL-166: every module re-parsed the whole tree on every 2.5 s poll; a client that
    names a tree's digest receives no nodes for it, and everything else is unchanged."""
    import time
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from harness.visualization import mount_visualization_routes

    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "one.txt").write_text("one")

    async def nothing():
        return None

    app = FastAPI()
    mount_visualization_routes(
        app,
        home=tmp_path / "home",
        journal=SimpleNamespace(catalog=lambda: []),
        root=tmp_path / "work",
        graph_reader=nothing,
        curator_reader=nothing,
        spend_reader=nothing,
        progress_reader=nothing,
    )
    with TestClient(app) as client:
        deadline = time.monotonic() + 10
        while (response := client.get("/v1/visualization")).status_code == 404:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        full = response.json()
        (project,) = full["projects"]
        assert [node["path"] for node in project["nodes"]] == [".", "one.txt"]
        held = client.get("/v1/visualization", params={"known": project["digest"]}).json()
    assert held["projects"] == [{**project, "nodes": None}]
    assert {**held, "projects": None, "observed_at": None} == {
        **full,
        "projects": None,
        "observed_at": None,
    }
