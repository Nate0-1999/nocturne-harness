"""Repeat M3B3's frozen build on one disposable Palace; never fabricate metrics."""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import websockets

from harness.envelope import EnvelopeFactory
from harness.onboarding import load_config
from harness.spine_client import SpineClient


def files(root):
    return {
        str(path.relative_to(root)): path.read_text().splitlines()
        for path in root.rglob("*")
        if path.is_file()
        and not any(
            part.startswith(".") or part == "__pycache__" for part in path.relative_to(root).parts
        )
        and path.suffix in {".py", ".md", ".toml", ".txt", ".ini", ".html"}
    }


async def run(args):
    config = load_config(home=args.home)
    assert config.principal_id.startswith("nocturne-verification-")
    root = args.workspace.resolve()
    root.mkdir(parents=True, exist_ok=False)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    args.output.mkdir(parents=True, exist_ok=True)
    thread = str(uuid4())
    factory = EnvelopeFactory(machine_id=config.machine_id, agent_id="m3ll-benchmark")
    prompt = Path(__file__).with_name("benchmark_prompt.txt").read_text()
    acceptance = Path(__file__).parents[1] / "m3b3" / "acceptance.py"
    start = time.monotonic()
    summary = {
        "thread_id": thread,
        "workspace": str(root),
        "principal_id": config.principal_id,
        "started_at": datetime.now(UTC).isoformat(),
        "runs": [],
        "gates": [],
        "churn_lines": 0,
        "measurement": "text line additions/removals observed at tool events",
    }
    previous = {}
    boundary_runs = set()
    with (args.output / "wire.jsonl").open("w") as log:
        async with websockets.connect(args.url, max_size=None) as socket:

            async def send(kind, payload):
                await socket.send(factory.create(kind, payload, thread_id=thread).model_dump_json())

            await send(
                "thread.snapshot",
                {
                    "request": True,
                    "workspace_root": str(root),
                    "project_key": "m3ll-build",
                    "project_label": "Learning benchmark",
                },
            )
            while True:
                event = json.loads(await socket.recv())
                if event["type"] == "error":
                    raise RuntimeError(event["payload"])
                if event["type"] == "thread.snapshot":
                    break
            await send("prompt.submit", {"prompt": prompt})
            while True:
                event = json.loads(await socket.recv())
                log.write(json.dumps(event) + "\n")
                log.flush()
                kind, payload = event["type"], event["payload"]
                detail = payload.get("event", {})
                if detail.get("event_kind") == "boundary_judgment" and detail.get("needs_owner"):
                    boundary_runs.add(payload["run_id"])
                if (kind == "run.delta" and payload.get("kind") == "event") or kind == "run.done":
                    current = files(root)
                    for path in previous.keys() | current.keys():
                        diff = difflib.ndiff(previous.get(path, []), current.get(path, []))
                        summary["churn_lines"] += sum(line[:2] in {"+ ", "- "} for line in diff)
                    previous = current
                if kind == "gate.open":
                    added_back = [
                        card["memory_id"]
                        for card in payload["near_misses"]
                        if card["memory_id"] in args.add_back_memory
                    ]
                    summary["gates"].append(
                        {
                            "injection_id": payload["injection_id"],
                            "injected": [x["memory_id"] for x in payload["injected"]],
                            "near_misses": len(payload["near_misses"]),
                            "added_back": added_back,
                        }
                    )
                    # Explicitly reviewed lessons may be added back through the real gate.
                    await send(
                        "gate.commit",
                        {
                            "run_id": payload["run_id"],
                            "injection_id": payload["injection_id"],
                            "removed": [],
                            "added_back": added_back,
                        },
                    )
                if kind == "error":
                    raise RuntimeError(payload)
                if kind != "run.done":
                    continue
                summary["runs"].append(payload)
                check = subprocess.run(
                    [sys.executable, str(acceptance), str(root)], capture_output=True, text=True
                )
                result = check.stdout + check.stderr
                (args.output / f"acceptance-{len(summary['runs'])}.txt").write_text(result)
                summary.update(
                    seconds=time.monotonic() - start, acceptance_pass=check.returncode == 0
                )
                (args.output / "progress.json").write_text(json.dumps(summary, indent=2) + "\n")
                print(
                    json.dumps(
                        {
                            "run": len(summary["runs"]),
                            "stop": payload,
                            "acceptance_pass": check.returncode == 0,
                        }
                    ),
                    flush=True,
                )
                if check.returncode == 0:
                    break
                if payload["run_id"] in boundary_runs:
                    raise RuntimeError("Boundary review requires attention; progress is preserved.")
                failure = "\n".join(
                    line
                    for line in result.splitlines()
                    if line.startswith(
                        (
                            "FAIL:",
                            "ERROR:",
                            "AssertionError:",
                            "ImportError:",
                            "ModuleNotFoundError:",
                        )
                    )
                ).replace(sys.executable, "python")
                await send(
                    "prompt.submit",
                    {
                        "prompt": "The fixed external acceptance failed. "
                        f"Repair only files in {root}; "
                        "the external checker must not be edited. Run your standard-library "
                        "tests from the workspace root. Diagnostics:\n" + failure
                    },
                )
    summary.update(
        seconds=time.monotonic() - start,
        completed_at=datetime.now(UTC).isoformat(),
        acceptance_pass=True,
    )
    client = SpineClient(
        config.spine_url, token=config.spine_token, principal_id=config.principal_id
    )
    try:
        spend = await client.spend_table([UUID(thread)])
        summary["spend"] = spend.model_dump(mode="json") if spend else None
    finally:
        await client.aclose()
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", default="ws://127.0.0.1:8797/ws")
    parser.add_argument("--add-back-memory", action="append", default=[])
    asyncio.run(run(parser.parse_args()))
