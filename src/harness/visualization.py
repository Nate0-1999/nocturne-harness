"""M3VZ / ADR-018: recorded observations for the three read-only 3D modules."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import zlib
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException


def directory_tree(root: Path) -> dict:
    """Enumerate every entry, including empty/hidden folders; never follow links."""
    nodes = []
    errors = []
    pending = [root]
    while pending:
        path = pending.pop()
        relative = path.relative_to(root).as_posix()
        try:
            stat = path.lstat()
            kind = "link" if path.is_symlink() else "directory" if path.is_dir() else "file"
            nodes.append({"path": relative, "kind": kind, "bytes": stat.st_size})
            if kind == "directory":
                with os.scandir(path) as entries:
                    pending.extend(Path(entry.path) for entry in entries)
        except OSError as exc:
            errors.append({"path": relative, "error": str(exc)})
    return {"root": str(root), "nodes": sorted(nodes, key=lambda n: n["path"]), "errors": errors}


def observe_worker(
    output: Path, assignment: dict, location, state: str, presence=(), messages=()
) -> None:
    """Observe the worker's actual feet, without changing its tools or decisions."""
    path = output / "visualization.json"
    try:
        previous = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        previous = {}
    files = {item["path"]: item["ts"] for item in previous.get("touched_files", [])}
    for event in presence:
        if event.event in {"read", "write"} and event.path.is_file():
            files.setdefault(str(event.path), event.ts.isoformat())
    # A worker's turns are its model responses; each tool call happens at its response.
    responses = [message for message in messages if message.kind == "response"]
    value = {
        "id": assignment["origin_agent"],
        "thread_id": assignment["thread_id"],
        "parent_id": assignment["thread_id"],
        "root": str(location.workspace_root),
        "location": str(location.cwd),
        "workspace_root": str(location.workspace_root),
        "stage": assignment["stage"],
        "state": state,
        "touched_files": [{"path": path, "ts": ts} for path, ts in sorted(files.items())],
        "turns": [response.timestamp.isoformat() for response in responses],
        "tool_calls": [
            response.timestamp.isoformat()
            for response in responses
            for part in response.parts
            if part.part_kind == "tool-call"
        ],
    }
    if all(previous.get(key) == value[key] for key in value):
        return
    value["ts"] = datetime.now(UTC).isoformat()
    value["started_at"] = previous.get("started_at", value["ts"])
    try:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value))
        temporary.chmod(0o600)
        temporary.replace(path)
    except OSError:
        pass  # Observation failure must not interrupt the worker's actual work.


def _journal_file_touch(event: dict, cwd: str, ts: str, pending: dict, files: dict) -> None:
    """Project successful explicit file tools; never infer file I/O from shell text."""
    part = event.get("part", {})
    name, call_id = part.get("tool_name"), part.get("tool_call_id")
    if name not in {"read", "write", "edit"}:
        return
    if event.get("event_kind") == "function_tool_call":
        args = part.get("args", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                return
        path = args.get("path") if isinstance(args, dict) else None
        if isinstance(path, str) and path:
            pending[call_id] = os.path.normpath(os.path.join(cwd, path))
    elif event.get("event_kind") == "function_tool_result":
        path = pending.pop(call_id, None)
        content = part.get("content", "")
        if (
            path is not None
            and part.get("part_kind") == "tool-return"
            and part.get("outcome", "success") == "success"
            and not str(content).startswith(f"{name} refused:")
        ):
            files.setdefault(path, ts)


def work_observation(journal, home: Path, default_root: Path) -> dict:
    """Project durable thread events and the worker's own observations, never prompts."""
    agents = []
    roots = {str(default_root.resolve())}
    for entry in journal.catalog():
        if entry.workspace_root is None:
            continue
        roots.add(entry.workspace_root)
        state, waiting_since = "stopped", None
        pending, files, turns, tool_calls = {}, {}, [], []
        cwd = entry.workspace_root
        for line in journal.path_for_thread(entry.thread_id).read_text().splitlines():
            row = json.loads(line)
            cwd = row.get("current_location") or cwd
            event = row.get("event", {})
            stream = event.get("payload", {}).get("event", {})
            _journal_file_touch(stream, cwd, row["captured_at"], pending, files)
            if stream.get("event_kind") == "function_tool_call":
                tool_calls.append(row["captured_at"])
            if event.get("type") == "run.started":
                turns.append(row["captured_at"])
                state, waiting_since = "running", None
            elif event.get("type") == "gate.open":
                state, waiting_since = "waiting", row["captured_at"]
            elif event.get("type") == "gate.dismiss":
                state, waiting_since = "running", None
            elif event.get("type") == "run.done":
                state, waiting_since = "stopped", None
        if entry.proposed_response is not None:
            state, waiting_since = "waiting", entry.updated_at
        agents.append(
            {
                "id": entry.thread_id,
                "thread_id": entry.thread_id,
                "parent_id": None,
                "label": entry.title,
                "root": entry.workspace_root,
                "location": entry.current_location or entry.workspace_root,
                "state": state,
                "started_at": entry.created_at,
                "updated_at": entry.updated_at,
                "waiting_since": waiting_since,
                "cost_usd": None,
                "touched_files": [{"path": path, "ts": ts} for path, ts in sorted(files.items())],
                "turns": turns,
                "tool_calls": tool_calls,
            }
        )
    workers = {}
    for path in sorted((home / "symphonies").glob("**/visualization.json")):
        try:
            value = json.loads(path.read_text())
            meter_path = path.parent / "meter.json"
            meter = json.loads(meter_path.read_text()) if meter_path.exists() else {}
            # Judge seats share spend lineage but are distinct concurrent processes.
            key = f"{value['id']}/{path.parent.name}" if value["stage"] == "judge" else value["id"]
            value["id"] = key
            previous = workers.get(key)
            cost = None if meter.get("unpriced", True) else float(meter["cost_usd"])
            if previous is None:
                workers[key] = {
                    **value,
                    "started_at": value.get("started_at", value["ts"]),
                    "cost_usd": cost,
                }
            else:
                started = min(previous["started_at"], value.get("started_at", value["ts"]))
                total = (
                    None
                    if cost is None or previous["cost_usd"] is None
                    else (previous["cost_usd"] + cost)
                )
                files = {
                    item["path"]: item
                    for item in previous.get("touched_files", []) + value.get("touched_files", [])
                }
                history = {
                    field: sorted(previous.get(field, []) + value.get(field, []))
                    for field in ("turns", "tool_calls")
                }
                if value["ts"] > previous["ts"]:
                    workers[key].update(value)
                workers[key].update(
                    started_at=started,
                    cost_usd=total,
                    touched_files=list(files.values()),
                    **history,
                )
        except (OSError, ValueError, KeyError):
            continue  # A worker is atomically replacing its observation; next sample retries.
    for value in workers.values():
        roots.add(value["root"])
        agents.append(
            {
                **value,
                "label": value["id"].split("/")[-1],
                "updated_at": value["ts"],
                "waiting_since": None,
            }
        )
    return {"agents": agents, "projects": [directory_tree(Path(root)) for root in sorted(roots)]}


class VisualizationHistory:
    """Append-only observations; history before the first sample is explicitly absent."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS observation "
                "(ts TEXT PRIMARY KEY, digest TEXT NOT NULL, payload BLOB NOT NULL)"
            )
        path.chmod(0o600)

    def append(self, value: dict, ts: str) -> None:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        with sqlite3.connect(self.path) as db:
            last = db.execute("SELECT digest FROM observation ORDER BY ts DESC LIMIT 1").fetchone()
            if last is None or last[0] != digest:
                db.execute(
                    "INSERT INTO observation VALUES (?, ?, ?)", (ts, digest, zlib.compress(encoded))
                )

    def read(self, as_of: str | None = None) -> dict:
        with sqlite3.connect(self.path) as db:
            timeline = [r[0] for r in db.execute("SELECT ts FROM observation ORDER BY ts")]
            rows = db.execute(
                "SELECT ts, payload FROM observation WHERE (? IS NULL OR ts <= ?) ORDER BY ts",
                (as_of, as_of),
            ).fetchall()
        if not rows:
            raise HTTPException(404, "No recorded visualization state at this time.")
        trails = {}
        for ts, blob in rows:
            value = json.loads(zlib.decompress(blob))
            for agent in value["agents"]:
                point = {
                    "ts": ts,
                    "location": agent["location"],
                    "cost_usd": agent["cost_usd"],
                    "state": agent["state"],
                }
                points = trails.setdefault(agent["id"], [])
                if not points or any(
                    points[-1][key] != point[key] for key in ("location", "cost_usd", "state")
                ):
                    points.append(point)
        return {
            **value,
            "as_of": rows[-1][0],
            "live": as_of is None,
            "timeline": timeline,
            "recorded_since": timeline[0],
            "trails": trails,
        }


def mount_visualization_routes(
    app: FastAPI,
    *,
    home,
    journal,
    root,
    graph_reader,
    curator_reader,
    spend_reader,
    progress_reader,
) -> None:
    """New M3VZ route family; existing rack/rewind/tool functions stay independent."""
    history = VisualizationHistory(home / "visualization.sqlite3")
    task = None
    observed_at = None
    sampling_error = None

    async def sample():
        observation = await asyncio.to_thread(work_observation, journal, home, root)
        observation.update(palace=None, curation=None, errors=[])
        for field, reader in (
            ("palace", graph_reader),
            ("curation", curator_reader),
            ("spend", spend_reader),
            ("progress", progress_reader),
        ):
            try:
                result = await reader()
                result = None if result is None else result.model_dump(mode="json")
                if result is not None:
                    result.pop("as_of", None)
                observation[field] = result
            except Exception as exc:
                observation["errors"].append({"feed": field, "error": type(exc).__name__})
        costs = {
            str(row["thread_id"]): row.get("total_usd")
            for row in (observation.get("spend") or {}).get("threads", [])
        }
        for agent in observation["agents"]:
            if agent["parent_id"] is None:
                agent["cost_usd"] = costs.get(agent["thread_id"])
        observation.pop("spend", None)
        await asyncio.to_thread(history.append, observation, datetime.now(UTC).isoformat())

    async def observe():
        nonlocal observed_at, sampling_error
        while True:
            try:
                await sample()
                observed_at, sampling_error = datetime.now(UTC).isoformat(), None
            except (OSError, ValueError, sqlite3.Error) as exc:
                sampling_error = type(exc).__name__
            await asyncio.sleep(2)

    async def start():
        nonlocal task
        task = asyncio.create_task(observe())

    async def stop():
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @app.get("/v1/visualization")
    async def visualization_snapshot(as_of: str | None = None):
        if as_of not in {None, "now"}:
            try:
                instant = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
                if instant.tzinfo is None:
                    raise ValueError("timezone required")
                as_of = instant.astimezone(UTC).isoformat()
            except ValueError:
                raise HTTPException(422, "Choose a recorded time with a timezone.") from None
        else:
            as_of = None
        result = await asyncio.to_thread(history.read, as_of)
        if as_of is None:
            result["observed_at"] = observed_at
            if sampling_error:
                result["errors"].append({"feed": "observation", "error": sampling_error})
        return result

    app.router.add_event_handler("startup", start)
    app.router.add_event_handler("shutdown", stop)
