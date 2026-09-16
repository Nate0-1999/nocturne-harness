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
