"""The separate, private T3 conversation server and its scoped browser pairing."""

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from uuid import NAMESPACE_URL, uuid5

import httpx

from harness.envelope import StopReason
from harness.t3_client import TERMINAL, T3Client, T3Error, new_id
from harness.t3_front_session import FrontSession, unsubmitted_messages
from harness.t3_passthrough import T3PassThrough
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
        self.syncing = asyncio.Lock()
        self.shown = (None, None)
        self.through = T3PassThrough()

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
            # T3 0.1.11 permits 80 MiB of images per turn, base64 on one ACP line.
            # Accept its frame so the ordinary image validator can explain our smaller limit.
            self.listener = await asyncio.start_unix_server(
                self._session, path=self.socket_path, limit=128 * 1024 * 1024
            )
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

    async def browser_url(self, through=None, route="/"):
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
        origin = through or client.origin
        return origin + route + "#" + urlencode({"token": response.json()["credential"]})

    async def frame_url(self, page, thread=None, paired=False):
        """The same paired window, for the one Nocturne page allowed to host it (A-101).

        SD-124: with a journal thread it opens on T3's own address for that thread. A page that
        is already paired gets the address alone, or nothing when T3 cannot show the thread yet.
        """
        client = await self.client()
        await self.through.start(
            urlsplit(client.origin).port, page, self.root / "frame-port", client.environment_id
        )
        route = None
        row = next((r for r in self.journal.catalog() if r.thread_id == thread), None)
        if row is not None and not row.archived:
            try:
                async with self.syncing:
                    await self.sync_thread(client, row, opened=True)
            except (OSError, T3Error, httpx.HTTPError, TimeoutError):
                pass  # T3 still opens, on its own first screen.
            native = self.journal.front_thread(thread, client.environment_id)
            if native is not None:
                route = f"/{client.environment_id}/{quote(native, safe='')}"
        if paired:
            return route and self.through.origin + route
        return await self.browser_url(self.through.origin, route or "/")

    def open_thread(self):
        """The journal thread T3's page is on, once the journal holds that T3 thread (SD-124)."""
        native = self.through.thread
        if native is None or self._client is None:
            return None
        if self.shown[0] == native:
            return self.shown[1]
        environment = self._client.environment_id
        born_in_t3 = str(uuid5(NAMESPACE_URL, f"nocturne:t3:{environment}/{native}"))
        for thread in (native, born_in_t3):
            if (
                self.journal.path_for_thread(thread).exists()
                and self.journal.front_thread(thread, environment) == native
            ):
                self.shown = (native, thread)
                return thread
        return None

    async def follow_catalog(self, client):
        """Use T3's published project and session imports while its window is available."""
        seen = {}
        while self.running:
            for row in self.journal.catalog():
                if row.archived or seen.get(row.thread_id) == row.updated_at:
                    continue
                try:
                    async with self.syncing:
                        settled = await self.sync_thread(client, row)
                    if settled:
                        seen[row.thread_id] = row.updated_at
                except (OSError, T3Error, httpx.HTTPError, TimeoutError) as exc:
                    logging.getLogger(__name__).warning(
                        "T3 conversation sync: %s", type(exc).__name__
                    )
            await asyncio.sleep(3)

    async def sync_thread(self, client, row, opened=False):
        history = self.journal.current_thread(row.thread_id)
        if not history:
            return True
        native = self.journal.front_thread(row.thread_id, client.environment_id)
        users = [m for m in history.messages if m["role"] == "user"]
        if not users and native is None and not opened:
            # An empty thread gets its T3 thread only when the owner opens it (SD-124).
            return True
        if users and (
            users[-1].get("state") not in StopReason or history.messages[-1]["role"] != "assistant"
        ):
            return False
        if native is None:
            root = row.workspace_root or str(self.default_root)
            if not Path(root).is_dir():
                return True
            projects = (await client.orchestration_get("shell"))["projects"]
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
        transcript = await client.orchestration_get(f"threads/{quote(native, safe='')}/transcript")
        skipped = unsubmitted_messages(transcript, self.journal.front_prompts(row.thread_id))
        visible = [
            row["item"]["text"]
            for row in transcript["items"]
            if row["item"]["type"] == "user_message" and row["item"].get("messageId") not in skipped
        ]
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
        await self.through.close()
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
