"""The separate, private T3 conversation server and its scoped browser pairing."""

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, uuid5

import httpx

from harness.envelope import StopReason
from harness.t3_client import TERMINAL, T3Client, T3Error, new_id
from harness.t3_front_session import FrontSession
from harness.t3_server import T3Server

BROWSER_SCOPES = (
    "orchestration:read orchestration:operate terminal:read terminal:operate "
    "filesystem:read filesystem:write source-control:write"
).split()
OUT_OF_STEP = "Out of step · open in Nocturne · "


class FrontServer(T3Server):
    def _home_environment(self):
        return {"HOME": str(self.root), "NOCTURNE_HOME": str(self.home)}

    def __init__(self, home, loop, journal, default_root):
        super().__init__(home)
        self.root = self.root / "front"
        self.home = home
        self.loop = loop
        self.journal = journal
        self.default_root = default_root.resolve()
        self.listener = None
        self.directory = None
        self.connections = set()
        self.sync = None

    def _settings(self):
        # The entire inventory at the pin. No native binary discovery on this server.
        drivers = "codex claudeAgent cursor grok fx kiro muse pi opencode antigravity".split()
        instances = {
            name: {"driver": name, "enabled": False, "config": {"enabled": False}}
            for name in drivers
        }
        instances["nocturne"] = {
            "driver": "acpRegistry",
            "displayName": "Nocturne",
            "enabled": True,
            "config": {
                "source": "local",
                "commandPath": sys.executable,
                "commandArgs": ["-m", "harness.t3_acp", str(self.socket_path)],
            },
        }
        return {
            "providerInstances": instances,
            "defaultModelSelection": {"instanceId": "nocturne", "model": "default"},
            "enableProviderUpdateChecks": False,
            "continueThreadsAfterServerUpdate": False,
            "defaultAutoPull": False,
            "promptSuggestionsEnabled": False,
            "observability": {},
        }

    async def _start(self):
        if self.listener is None:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            # macOS sockaddr_un has a 104-byte path, including the terminator.
            parent = self.root if len(os.fsencode(self.root)) < 78 else None
            self.directory = tempfile.TemporaryDirectory(prefix="nt3-", dir=parent)
            self.socket_path = Path(self.directory.name) / "agent"
            self.listener = await asyncio.start_unix_server(self._session, path=self.socket_path)
        return await super()._start()

    async def _session(self, reader, writer):
        task = asyncio.current_task()
        self.connections.add(task)
        try:
            native = json.loads(await reader.readline())
            await FrontSession(self, native, reader, writer).serve()
        except (ValueError, OSError, EOFError):
            pass
        finally:
            writer.close()
            self.connections.discard(task)

    async def _authenticate(self, port, settings, env, code):
        client = T3Client(port)
        await client.authenticate(code, scopes=" ".join([*BROWSER_SCOPES, "access:write"]))
        return client

    async def browser_url(self):
        client = await self.client()
        config = await client.call("server.getConfig", {})
        enabled = [row["instanceId"] for row in config["providers"] if row["enabled"]]
        if enabled != ["nocturne"]:
            # WALL tool calls / SD-114: a front composer must offer only our agent.
            raise T3Error("The front server did not offer Nocturne as its only agent.")
        if self.sync is None or self.sync.done():
            self.sync = asyncio.create_task(self.follow_catalog(client))
        async with httpx.AsyncClient(trust_env=False) as http:
            response = await http.post(
                client.origin + "/api/auth/pairing-token",
                headers={"Authorization": f"Bearer {client.session}"},
                json={"scopes": BROWSER_SCOPES, "label": "Nocturne conversation window"},
            )
        if response.status_code != 200:
            raise T3Error("T3 could not pair the conversation window.")
        return client.origin + "/#" + urlencode({"token": response.json()["credential"]})

    async def follow_catalog(self, client):
        """Use T3's published project and session imports while its window is available."""
        seen = {}
        while self.running:
            for row in self.journal.catalog():
                if row.archived or seen.get(row.thread_id) == row.updated_at:
                    continue
                try:
                    if await self.sync_thread(client, row):
                        seen[row.thread_id] = row.updated_at
                except (OSError, T3Error, httpx.HTTPError, TimeoutError) as exc:
                    logging.getLogger(__name__).warning(
                        "T3 conversation sync: %s", type(exc).__name__
                    )
            await asyncio.sleep(3)

    async def sync_thread(self, client, row):
        history = self.journal.current_thread(row.thread_id)
        if not history:
            return True
        native = self.journal.front_thread(row.thread_id, client.environment_id)
        users = [m for m in history.messages if m["role"] == "user"]
        if not users and native is None:
            return True
        if users and (
            users[-1].get("state") not in StopReason or history.messages[-1]["role"] != "assistant"
        ):
            return False
        if native is None:
            root = row.workspace_root or str(self.default_root)
            if not Path(root).is_dir():
                return True
            async with httpx.AsyncClient(trust_env=False) as http:
                shell = await http.get(
                    client.origin + "/api/orchestration/shell",
                    headers={
                        "Authorization": f"Bearer {client.session}",
                        "x-t3-orchestration-protocol": "2",
                    },
                )
                shell.raise_for_status()
                projects = shell.json()["projects"]
            project = next(
                (
                    p["id"]
                    for p in projects
                    if p["workspaceRoot"] == root and not p.get("archivedAt")
                ),
                None,
            )
            if project is None:
                project = new_id()
                await client.call(
                    "projects.mutate",
                    dict(
                        type="project.create",
                        commandId=new_id(),
                        projectId=project,
                        title=row.project_label or Path(root).name or root,
                        workspaceRoot=root,
                    ),
                )
            native = row.thread_id
            await client.call(
                "orchestration.launchThread",
                dict(
                    commandId=str(uuid5(NAMESPACE_URL, f"nocturne:window:{native}")),
                    projectId=project,
                    threadId=native,
                    title=row.title,
                    generateTitle=False,
                    modelSelection={"instanceId": "nocturne", "model": "default"},
                    runtimeMode="approval-required",
                    interactionMode="default",
                    workspaceStrategy={"type": "root"},
                ),
            )
            self.journal.bind_front_window(row.thread_id, client.environment_id)
        projection = await client.call("orchestration.getThreadProjection", {"threadId": native})
        if any(r["status"] not in TERMINAL for r in projection["runs"]):
            return False
        visible = [m["text"] for m in projection["messages"] if m["role"] == "user"]
        title = projection["thread"]["title"]
        if visible != [m["content"] for m in users[: len(visible)]]:
            if not title.startswith(OUT_OF_STEP):
                await client.dispatch(native, "thread.metadata.update", title=OUT_OF_STEP + title)
            return True  # follow_catalog waits for the next journal change.
        if title.startswith(OUT_OF_STEP):
            await client.dispatch(
                native, "thread.metadata.update", title=title.removeprefix(OUT_OF_STEP)
            )
        if len(visible) < len(users):
            prompt = users[len(visible)]
            if prompt.get("state") not in StopReason:
                return False
            # ACP sees the original journal ID and replays the settled answer without a run.
            await client.message(
                native,
                "nocturne-journal-" + prompt["message_id"],
                prompt["content"],
                {"instanceId": "nocturne", "model": "default"},
            )
            return False
        return True

    async def close(self):
        if self.sync is not None:
            self.sync.cancel()
            await asyncio.gather(self.sync, return_exceptions=True)
            self.sync = None
        try:
            await super().close()
        finally:
            if self.listener is not None:
                self.listener.close()
                await self.listener.wait_closed()
                self.listener = None
            tasks = list(self.connections)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.directory is not None:
                self.directory.cleanup()
                self.directory = None
