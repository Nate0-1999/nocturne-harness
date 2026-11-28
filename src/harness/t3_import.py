"""Adopt only the chosen private T3 project's native conversations (SD-130)."""

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid5

from harness.envelope import generate_ulid
from harness.t3_client import T3Error
from harness.t3_sources import TOOLS, resolve_offer, sources


async def projects(server):
    client = await server.client()
    scan = await client.call("agentSessions.scan", {})
    return [
        {
            "folder": row["path"],
            "tools": [TOOLS[t][0] for t in row["sources"]],
            "count": row["threadCount"],
        }
        for row in scan["candidates"]
        if row["sources"] and set(row["sources"]) <= TOOLS.keys()
    ]


def history(items):
    messages = []
    run = None
    for item in items:
        if item["runId"] is not None:
            continue
        if item["type"] == "system_notice":
            content = item["message"]
        elif item["type"] in {"user_message", "assistant_message"}:
            content = item["text"]
        else:
            continue
        stamp = datetime.fromisoformat(item["startedAt"])
        user = item["type"] == "user_message"
        if user or run is None:
            run = generate_ulid(stamp)
        message = dict(message_id=generate_ulid(stamp), run_id=run, content=content, imported=True)
        if user:
            message.update(role="user", state="end_turn", model_visible=False)
        else:
            message.update(role="assistant", thinking="", events=[], partial=False)
        messages.append(message)
    return messages


async def bring_project(server, journal, folder, *, register=None):
    if folder not in {p["folder"] for p in await projects(server)}:
        raise T3Error("This project is no longer available. Refresh the project list.")
    if not Path(folder).is_dir():
        raise T3Error("The original project folder has moved.")
    client = await server.client()
    project = await client.workspace_project(folder, Path(folder).name)
    result = await client.call(
        "agentSessions.import",
        {
            "projectId": project,
            "expectedWorkspaceRoot": folder,
        },
    )
    shell = await client.orchestration_get("shell")
    accounts = {s["tool"]: s["account"] for s in await sources(server)}
    environment = hashlib.sha256(client.environment_id.encode()).hexdigest()
    adopted = []
    for thread in shell["threads"]:
        tool = thread["providerInstanceId"]
        if (
            thread["projectId"] != project
            or tool not in TOOLS
            or not thread["id"].startswith(f"import:{tool}:")
        ):
            continue
        session = thread["id"].removeprefix(f"import:{tool}:")
        thread_id = str(uuid5(NAMESPACE_URL, f"nocturne:import:{environment}/{tool}/{session}"))
        if journal.path_for_thread(thread_id).exists():
            if register:
                register(thread_id)
            adopted.append(thread_id)
            continue
        projection = await client.call(
            "orchestration.getThreadProjection", {"threadId": thread["id"]}
        )
        original = projection["thread"]
        if original.get("historyOrigin") != "v1_import" or original["projectId"] != project:
            continue
        # At the pin a run-less import exposes its active provider ID on the thread,
        # while the public projection's providerThreads collection can still be empty.
        provider_thread = original.get("activeProviderThreadId")
        if (
            provider_thread
            != f"provider-thread:provider:{tool}:provider-instance:{tool}:native-thread:{session}"
        ):
            raise T3Error("T3 could not identify the original tool session.")
        slug = original["modelSelection"]["model"]
        account = accounts.get(tool)
        binding = dict(
            source=f"subscription:{tool}/{account}/{slug}"
            if account
            else f"subscription:{tool}/{slug}",
            environment=environment,
            native_project=project,
            native_thread=thread["id"],
            native_session=session,
            provider_thread=provider_thread,
            tool=tool,
            location=original.get("worktreePath") or folder,
        )
        transcript = await client.orchestration_get(
            f"threads/{quote(thread['id'], safe='')}/transcript"
        )
        messages = history(entry["item"] for entry in transcript["items"])
        journal.adopt_subscription(thread_id, binding, folder, original["title"], messages)
        if register:
            register(thread_id)
        adopted.append(thread_id)
    return {"threads": adopted, "skipped": result["skippedCount"]}


async def check_original(server, binding, location):
    """A vanished native transcript must never fall through to a fresh provider session."""
    if location != binding["location"] or not Path(location).is_dir():
        raise T3Error("The original conversation folder has moved.")
    client = await server.client()
    if hashlib.sha256(client.environment_id.encode()).hexdigest() != binding["environment"]:
        raise T3Error("The original subscription server is unavailable.")
    session = str(UUID(binding["native_session"]))
    home = Path(client.native_env["HOME"])
    if binding["tool"] == "codex":
        root = home / ".codex/sessions"
        patterns = (
            f"*/*/*/rollout-*-{session}.jsonl",
            f"*/*/*/rollout-*-{session}.jsonl.zst",
            f"*/*/*/rollout-*-{session}_*.jsonl",
            f"*/*/*/rollout-*-{session}_*.jsonl.zst",
        )
    else:
        root = home / ".claude/projects"
        patterns = (f"*/{session}.jsonl",)
    if not await asyncio.to_thread(
        lambda: any(p.is_file() for pat in patterns for p in root.glob(pat))
    ):
        raise T3Error("The original tool session is missing.")
    await resolve_offer(server, binding["source"])
    projection = await client.call(
        "orchestration.getThreadProjection", {"threadId": binding["native_thread"]}
    )
    thread = projection["thread"]
    if thread["activeProviderThreadId"] != binding["provider_thread"]:
        raise T3Error("The original tool session is missing.")
    if thread["runtimeMode"] != "approval-required":
        await client.dispatch(
            thread["id"], "thread.runtime-mode.set", runtimeMode="approval-required"
        )
