"""M3VZ / ADR-018: recorded observations for the three read-only 3D modules."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import threading
import time
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from stat import S_ISDIR, S_ISLNK

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

# M3HW: re-walking project trees may use at most this share of one core.
_WALK_SHARE = 0.02
# M3HW: a stored tree is a delta on its root's previous one, with a whole tree after this many.
_TREE_KEYFRAME_AFTER = 64


def directory_tree(root: Path) -> dict:
    """Enumerate every entry, including empty/hidden folders; never follow links.

    M3HW: one lstat per entry through scandir; the pathlib walk took ~1 s per 30,000 entries.
    """
    nodes = []
    errors = []
    pending = [(str(root), ".", None)]
    while pending:
        path, relative, entry = pending.pop()
        try:
            status = os.lstat(path) if entry is None else entry.stat(follow_symlinks=False)
            mode = status.st_mode
            kind = "link" if S_ISLNK(mode) else "directory" if S_ISDIR(mode) else "file"
            nodes.append({"path": relative, "kind": kind, "bytes": status.st_size})
            if kind == "directory":
                prefix = "" if relative == "." else f"{relative}/"
                with os.scandir(path) as entries:
                    pending.extend((item.path, prefix + item.name, item) for item in entries)
        except OSError as exc:
            errors.append({"path": relative, "error": str(exc)})
    tree = {"root": str(root), "nodes": sorted(nodes, key=lambda n: n["path"]), "errors": errors}
    return {**tree, "digest": _tree_digest(tree)}


def _tree_digest(tree: dict) -> str:
    """M3HW: a tree's identity is its content, so one stored copy serves every row that has it."""
    content = json.dumps([tree["nodes"], tree["errors"]], separators=(",", ":")).encode()
    return hashlib.sha256(content).hexdigest()


def _project_trees(roots: set[str], cache: dict) -> list[dict]:
    """M3HW: a tree is walked when its root first appears, then again only within the budget.

    Walking every root on every 2 s sample held a core at ~30% for one 30,000-entry repository
    and at 100% once seven Symphonies' worktrees (290,000 entries) outlasted the interval.
    """
    roots = {root for root in roots if os.path.isdir(root)}  # a removed worktree is no project
    trees = cache.setdefault("trees", {})
    for root in set(trees) - roots:
        del trees[root]
    due = time.monotonic() >= cache.get("next_walk", 0.0)
    spent = 0.0
    for root in sorted(roots):
        if due or root not in trees:
            started = time.monotonic()
            trees[root] = directory_tree(Path(root))
            spent += time.monotonic() - started
    if spent:
        cache["next_walk"] = time.monotonic() + spent / _WALK_SHARE
    return [trees[root] for root in sorted(roots)]


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


def work_observation(
    journal, home: Path, default_root: Path, folds: dict | None = None, trees: dict | None = None
) -> dict:
    """Project durable thread events and the worker's own observations, never prompts.

    M3EX-37: with `folds`, each append-only thread file is read from where the last
    sample stopped; re-parsing every journal every 2 s held gigabytes.
    """
    agents = []
    roots = {str(default_root.resolve())}
    folds = {} if folds is None else folds
    for entry in journal.catalog():
        if entry.workspace_root is None:
            continue
        roots.add(entry.workspace_root)
        path = journal.path_for_thread(entry.thread_id)
        fold = folds.get(entry.thread_id)
        if fold is None or fold["offset"] > path.stat().st_size:
            fold = {
                "offset": 0,
                "cwd": entry.workspace_root,
                "state": "stopped",
                "waiting_since": None,
                "pending": {},
                "files": {},
                "turns": [],
                "tool_calls": [],
            }
        with path.open("rb") as handle:
            handle.seek(fold["offset"])
            chunk = handle.read()
        complete = chunk[: chunk.rfind(b"\n") + 1]
        fold["offset"] += len(complete)
        folds[entry.thread_id] = fold
        pending, files, turns, tool_calls = (
            fold["pending"],
            fold["files"],
            fold["turns"],
            fold["tool_calls"],
        )
        for line in complete.splitlines():
            row = json.loads(line)
            fold["cwd"] = row.get("current_location") or fold["cwd"]
            event = row.get("event", {})
            stream = event.get("payload", {}).get("event", {})
            _journal_file_touch(stream, fold["cwd"], row["captured_at"], pending, files)
            if stream.get("event_kind") == "function_tool_call":
                tool_calls.append(row["captured_at"])
            if event.get("type") == "run.started":
                turns.append(row["captured_at"])
                fold["state"], fold["waiting_since"] = "running", None
            elif event.get("type") == "gate.open":
                fold["state"], fold["waiting_since"] = "waiting", row["captured_at"]
            elif event.get("type") == "gate.dismiss":
                fold["state"], fold["waiting_since"] = "running", None
            elif event.get("type") == "run.done":
                fold["state"], fold["waiting_since"] = "stopped", None
        state, waiting_since = fold["state"], fold["waiting_since"]
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
                "turns": list(turns),
                "tool_calls": list(tool_calls),
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
    return {"agents": agents, "projects": _project_trees(roots, {} if trees is None else trees)}


def _encode(value) -> bytes:
    return zlib.compress(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _decode(blob: bytes):
    return json.loads(zlib.decompress(blob))


def _tree_delta(before: list[dict], after: list[dict]) -> dict:
    old = {node["path"]: node for node in before}
    kept = {node["path"] for node in after}
    return {
        "set": [node for node in after if old.get(node["path"]) != node],
        "drop": [path for path in old if path not in kept],
    }


class VisualizationHistory:
    """Append-only observations; history before the first sample is explicitly absent.

    M3HW: every changed sample stored every whole tree (1 GB in a day). A row now names its
    trees by digest; a tree is written once, then as the entries that changed against its
    root's previous tree (a keyframe every 64), and each row keeps its trail points beside
    its payload, so a scrub folds trails without decompressing every earlier row. Rows older
    than the retention window leave with the trees only they needed. Rows written before
    M3HW carry whole trees and no trail; they are read as they are and age out the same way.
    """

    def __init__(self, path: Path, retention: timedelta | None = None):
        self.path = path
        self.retention = retention
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA auto_vacuum = INCREMENTAL")  # a new file only; see _prune
            db.execute(
                "CREATE TABLE IF NOT EXISTS observation "
                "(ts TEXT PRIMARY KEY, digest TEXT NOT NULL, payload BLOB NOT NULL)"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(observation)")}
            for column in ("trail", "trees"):
                if column not in columns:
                    db.execute(f"ALTER TABLE observation ADD COLUMN {column}")
            db.execute(
                "CREATE TABLE IF NOT EXISTS tree (digest TEXT PRIMARY KEY, base TEXT, "
                "depth INTEGER NOT NULL, payload BLOB NOT NULL)"
            )
        path.chmod(0o600)
        # M3EX-37: a live read folds only rows newer than the last one; decompressing
        # every recorded observation on each 2.5 s poll held gigabytes.
        self._live_lock = threading.Lock()
        self._live: dict = {"after": None, "timeline": [], "trails": {}, "last": None}
        self._bases: dict[str, tuple[str, dict, int]] = {}  # root -> its last stored tree
        self._trees: dict[str, dict] = {}  # digest -> tree, the few most recently rebuilt
        self._tree_lock = threading.Lock()  # the sampler writes trees while polls read them
        self._pruned_at: datetime | None = None

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)  # a one-time VACUUM may hold the file

    def append(self, value: dict, ts: str) -> None:
        refs = [
            {"root": project["root"], "tree": project.get("digest") or _tree_digest(project)}
            for project in value["projects"]
        ]
        encoded = json.dumps(
            {**value, "projects": refs}, sort_keys=True, separators=(",", ":")
        ).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        with self._connect() as db:
            last = db.execute("SELECT digest FROM observation ORDER BY ts DESC LIMIT 1").fetchone()
            if last is not None and last[0] == digest:
                return
            with self._tree_lock:
                for project, ref in zip(value["projects"], refs, strict=True):
                    self._store_tree(db, project, ref["tree"])
                # A root that left keeps no tree in memory (M3HW: a leak guard).
                self._bases = {ref["root"]: self._bases[ref["root"]] for ref in refs}
            trail = [
                [agent["id"], agent["location"], agent["cost_usd"], agent["state"]]
                for agent in value["agents"]
            ]
            db.execute(
                "INSERT INTO observation (ts, digest, payload, trail, trees) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    ts,
                    digest,
                    zlib.compress(encoded),
                    _encode(trail),
                    ",".join(sorted({ref["tree"] for ref in refs})),
                ),
            )
        self._prune(ts)

    def _store_tree(self, db: sqlite3.Connection, tree: dict, digest: str) -> None:
        stored = db.execute("SELECT depth FROM tree WHERE digest = ?", (digest,)).fetchone()
        if stored is None:
            payload, base, depth = {"nodes": tree["nodes"], "errors": tree["errors"]}, None, 0
            previous = self._bases.get(tree["root"])
            if previous is not None and previous[2] < _TREE_KEYFRAME_AFTER:
                delta = _tree_delta(previous[1]["nodes"], tree["nodes"])
                if len(delta["set"]) + len(delta["drop"]) < len(tree["nodes"]) // 4:
                    payload = {**delta, "errors": tree["errors"]}
                    base, depth = previous[0], previous[2] + 1
            db.execute(
                "INSERT INTO tree VALUES (?, ?, ?, ?)", (digest, base, depth, _encode(payload))
            )
        else:
            depth = stored[0]
        self._bases[tree["root"]] = (digest, tree, depth)

    def _tree(self, db: sqlite3.Connection, digest: str) -> dict:
        for stored, tree, _depth in self._bases.values():
            if stored == digest:  # the tree this process just wrote: no second copy
                return {"nodes": tree["nodes"], "errors": tree["errors"]}
        chain = []
        cursor = digest
        while cursor is not None and cursor not in self._trees:
            base, payload = db.execute(
                "SELECT base, payload FROM tree WHERE digest = ?", (cursor,)
            ).fetchone()
            chain.append(_decode(payload))
            cursor = base
        tree = self._trees.get(cursor, {"nodes": [], "errors": []})
        if chain:
            nodes = {node["path"]: node for node in tree["nodes"]}
            for part in reversed(chain):
                if "nodes" in part:
                    nodes = {node["path"]: node for node in part["nodes"]}
                    continue
                for path in part["drop"]:
                    nodes.pop(path, None)
                nodes.update((node["path"], node) for node in part["set"])
            tree = {
                "nodes": sorted(nodes.values(), key=lambda n: n["path"]),
                "errors": part["errors"],
            }
            self._trees[digest] = tree
            while len(self._trees) > 4:
                self._trees.pop(next(iter(self._trees)))
        return tree

    def _observation(self, db: sqlite3.Connection, blob: bytes) -> dict:
        value = _decode(blob)
        with self._tree_lock:
            value["projects"] = [
                project
                if "nodes" in project
                else {
                    "root": project["root"],
                    "digest": project["tree"],
                    **self._tree(db, project["tree"]),
                }
                for project in value["projects"]
            ]
        return value

    def _trails(self, db: sqlite3.Connection, trails: dict, after: str | None, until: str | None):
        rows = db.execute(
            "SELECT ts, trail, CASE WHEN trail IS NULL THEN payload END FROM observation "
            "WHERE (? IS NULL OR ts > ?) AND (? IS NULL OR ts <= ?) ORDER BY ts",
            (after, after, until, until),
        )
        timeline = []
        for ts, trail, payload in rows:
            points = (
                _decode(trail)
                if trail is not None
                else [
                    [agent["id"], agent["location"], agent["cost_usd"], agent["state"]]
                    for agent in _decode(payload)["agents"]
                ]
            )
            _fold_trails(trails, ts, points)
            timeline.append(ts)
        return timeline

    def read(self, as_of: str | None = None) -> dict:
        if as_of is None:
            return self._read_live()
        with self._connect() as db:
            timeline = [r[0] for r in db.execute("SELECT ts FROM observation ORDER BY ts")]
            last = db.execute(
                "SELECT ts, payload FROM observation WHERE ts <= ? ORDER BY ts DESC LIMIT 1",
                (as_of,),
            ).fetchone()
            if last is None:
                raise HTTPException(404, "No recorded visualization state at this time.")
            trails: dict = {}
            self._trails(db, trails, None, as_of)
            value = self._observation(db, last[1])
        return {
            **value,
            "as_of": last[0],
            "live": False,
            "timeline": timeline,
            "recorded_since": timeline[0],
            "trails": trails,
        }

    def _read_live(self) -> dict:
        with self._live_lock:
            live = self._live
            with self._connect() as db:
                timeline = self._trails(db, live["trails"], live["after"], None)
                if timeline:
                    live["timeline"].extend(timeline)
                    live["after"] = timeline[-1]
                    (blob,) = db.execute(
                        "SELECT payload FROM observation WHERE ts = ?", (live["after"],)
                    ).fetchone()
                    live["last"] = (live["after"], self._observation(db, blob))
            if live["last"] is None:
                raise HTTPException(404, "No recorded visualization state at this time.")
            return {
                **live["last"][1],
                "errors": list(live["last"][1].get("errors", [])),  # callers append to it
                "as_of": live["last"][0],
                "live": True,
                "timeline": list(live["timeline"]),
                "recorded_since": live["timeline"][0],
                "trails": {key: list(points) for key, points in live["trails"].items()},
            }

    def _prune(self, ts: str) -> None:
        """Keep the retention window: at most every ten minutes, drop older rows and the trees
        only they needed, then return the space (a store from before M3HW is vacuumed once)."""
        now = datetime.fromisoformat(ts)
        if self.retention is None or (
            self._pruned_at is not None and now - self._pruned_at < timedelta(minutes=10)
        ):
            return
        self._pruned_at = now
        with self._connect() as db:
            cutoff = (now - self.retention).isoformat()
            if not db.execute("DELETE FROM observation WHERE ts < ?", (cutoff,)).rowcount:
                return
            needed = set()
            for (trees,) in db.execute("SELECT trees FROM observation WHERE trees IS NOT NULL"):
                needed.update(filter(None, trees.split(",")))
            bases = dict(db.execute("SELECT digest, base FROM tree"))
            kept = set()
            for digest in needed:
                while digest is not None and digest not in kept:
                    kept.add(digest)
                    digest = bases.get(digest)
            db.executemany(
                "DELETE FROM tree WHERE digest = ?", [(d,) for d in bases if d not in kept]
            )
            db.commit()
            if db.execute("PRAGMA auto_vacuum").fetchone()[0] == 2:
                db.execute("PRAGMA incremental_vacuum").fetchall()  # one page per step
            else:
                db.execute("PRAGMA auto_vacuum = INCREMENTAL")
                db.execute("VACUUM")
        with self._live_lock:
            self._live = {"after": None, "timeline": [], "trails": {}, "last": None}


def _fold_trails(trails: dict, ts: str, points: list) -> None:
    for agent_id, location, cost_usd, state in points:
        point = {"ts": ts, "location": location, "cost_usd": cost_usd, "state": state}
        trail = trails.setdefault(agent_id, [])
        if not trail or any(
            trail[-1][key] != point[key] for key in ("location", "cost_usd", "state")
        ):
            trail.append(point)


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
    retention: timedelta | None = None,
) -> None:
    """New M3VZ route family; existing rack/rewind/tool functions stay independent."""
    history = VisualizationHistory(home / "visualization.sqlite3", retention)
    task = None
    observed_at = None
    sampling_error = None
    folds: dict = {}
    trees: dict = {}

    feeds = (
        ("palace", graph_reader),
        ("curation", curator_reader),
        ("spend", spend_reader),
        ("progress", progress_reader),
    )
    reads: dict = {}  # feed -> its Palace read in flight
    held: dict = {}  # feed -> its last good value

    async def sample():
        observation = await asyncio.to_thread(work_observation, journal, home, root, folds, trees)
        observation.update(palace=None, curation=None, errors=[])
        # M3HW (found by M3LV): four Palace reads in a row held the local observation for the sum
        # of their latencies (90 s on a slow Palace). Each read runs on its own, a sample waits at
        # most a second, and a read still running leaves its feed's last good value in place.
        for field, reader in feeds:
            if field not in reads:
                reads[field] = asyncio.create_task(reader())
        await asyncio.wait(reads.values(), timeout=1)
        for field, _reader in feeds:
            if reads[field].done():
                read = reads.pop(field)
                try:
                    result = read.result()
                    result = None if result is None else result.model_dump(mode="json")
                    if result is not None:
                        result.pop("as_of", None)
                    held[field] = result
                except Exception as exc:
                    held.pop(field, None)
                    observation["errors"].append({"feed": field, "error": type(exc).__name__})
            if field in held:
                observation[field] = held[field]
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
        for pending in (task, *reads.values()):
            if pending is not None:
                pending.cancel()
        await asyncio.gather(*(t for t in (task, *reads.values()) if t), return_exceptions=True)

    @app.get("/v1/visualization")
    async def visualization_snapshot(as_of: str | None = None, known: str | None = None):
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
        # M3HW: a client that already holds a tree names its digest and receives no nodes for
        # it; three modules re-parsing a 3 MB tree every 2.5 s swung the tab's heap by 500 MB.
        held = set(known.split(",")) if known else set()
        result["projects"] = [
            {**project, "nodes": None} if project.get("digest") in held else project
            for project in result["projects"]
        ]
        return JSONResponse(result)  # already JSON: skip the per-node encoder on the loop

    app.router.add_event_handler("startup", start)
    app.router.add_event_handler("shutdown", stop)
