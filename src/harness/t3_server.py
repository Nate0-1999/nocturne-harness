"""The daemon's private foreground T3 server (A-095, F256)."""

import asyncio
import contextlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from harness.t3_client import VERSION, T3Client, T3Error


def _native_tools() -> dict:
    home = Path.home()
    codex = shutil.which("codex")
    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app")
    if not codex and (bundled / "Contents/MacOS/codex").is_file():
        codex = str(bundled / "Contents/MacOS/codex")
    claude = shutil.which("claude")
    if not claude:
        builds = (home / "Library/Application Support/Claude/claude-code").glob(
            "*/*/claude.app/Contents/MacOS/claude"
        )
        latest = max(builds, key=lambda path: path.stat().st_mtime, default=None)
        claude = str(latest) if latest else None
    result = {}
    for driver, binary in (("codex", codex), ("claudeAgent", claude)):
        config = {"binaryPath": binary or ("claude" if driver == "claudeAgent" else "codex")}
        if driver == "codex":
            config["setupMode"] = "existing"
        result[driver] = {"driver": driver, "enabled": bool(binary), "config": config}
    for driver in ("antigravity", "cursor", "grok", "fx", "kiro", "muse", "pi", "opencode"):
        result[driver] = {"driver": driver, "enabled": False, "config": {"enabled": False}}
    return result


def _descendants(root: int, known: dict[int, str]) -> dict[int, str]:
    # Only process identities are read. Children can put themselves in new process groups.
    rows = subprocess.check_output(
        ["ps", "-axo", "pid=,ppid=,pgid=,stat=,lstart="], text=True, timeout=4
    )
    table = {}
    for line in rows.splitlines():
        pid, parent, group, state, started = line.split(None, 4)
        if not state.startswith("Z"):
            table[int(pid)] = (int(parent), int(group), started)
    marked = {
        pid for pid, (_, group, birth) in table.items() if known.get(pid) == birth or group == root
    }
    while children := {pid for pid, (parent, _, _) in table.items() if parent in marked} - marked:
        marked.update(children)
    return {pid: table[pid][2] for pid in marked}


class T3Server:
    def __init__(self, home: Path):
        self.root = home / "t3"
        self.binary = self.root / "install" / VERSION / "t3"
        self._lock = asyncio.Lock()
        self._process = None
        self._reader = None
        self._watcher = None
        self._client = None
        self._owned: dict[int, str] = {}

    async def client(self) -> T3Client:
        async with self._lock:
            if self._process and self._process.returncode is None and self._client:
                return self._client
            await self._stop()
            if not self.binary.is_file():
                raise T3Error(f"T3 {VERSION} is missing. Run nocturne t3 install.")
            try:
                async with asyncio.timeout(90):
                    self._client = await self._start()
            except BaseException:
                await self._stop()
                raise
            return self._client

    async def _start(self) -> T3Client:
        state = self.root / "state"
        work = self.root / "workspace"
        tmp = self.root / "tmp"
        for folder in (self.root, state, state / "userdata", work, tmp):
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            folder.chmod(0o700)
        settings = {
            "providerInstances": _native_tools(),
            "enableProviderUpdateChecks": False,
            "continueThreadsAfterServerUpdate": False,
            "defaultAutoPull": False,
            "promptSuggestionsEnabled": False,
            "observability": {},
        }
        (state / "userdata/settings.json").write_text(json.dumps(settings))
        env = {
            "HOME": str(Path.home()),
            "SHELL": "/bin/sh",
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin",
            "TMPDIR": str(tmp),
            "T3CODE_HOME": str(state),
            "T3CODE_LAN": "false",
            "T3CODE_TAILSCALE_SERVE": "false",
            "T3CODE_TELEMETRY_ENABLED": "false",
            "T3CODE_LOG_WS_EVENTS": "false",
            "T3CODE_CODEX_PROBE_TIMEOUT_MS": "60000",
            "T3CODE_AUTO_BOOTSTRAP_PROJECT_FROM_CWD": "false",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_AUTOUPDATER": "1",
            "DISABLE_TELEMETRY": "1",
            "NO_COLOR": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        while True:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            if port > 20000:
                break
        proc = await asyncio.create_subprocess_exec(
            self.binary,
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-browser",
            cwd=work,
            env=env,
            start_new_session=True,
            umask=0o077,
            stdin=subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self._process = proc
        self._watcher = asyncio.create_task(self._watch(proc.pid))
        code = asyncio.get_running_loop().create_future()

        async def drain():
            try:
                async for raw in proc.stdout:
                    if code.done():
                        continue
                    match = re.search(rb"Pairing URL:\s+(http://[^\s]+)", raw)
                    if match:
                        url = urlsplit(match[1].decode("ascii"))
                        if url.netloc == f"127.0.0.1:{port}":
                            tokens = parse_qs(url.fragment).get("token")
                            if tokens:
                                code.set_result(tokens[0])
            finally:
                if not code.done():
                    code.set_exception(T3Error("T3 exited before local authentication."))

        self._reader = asyncio.create_task(drain())
        client = T3Client(port)
        await client.authenticate(await code)
        return client

    async def _watch(self, pid):
        while True:
            self._owned.update(await asyncio.to_thread(_descendants, pid, self._owned.copy()))
            await asyncio.sleep(0.35)

    async def close(self):
        async with self._lock:
            await self._stop()

    async def _stop(self):
        proc = self._process
        if proc is None:
            return
        self._watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._watcher
        self._owned.update(await asyncio.to_thread(_descendants, proc.pid, self._owned))
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
        for sig in (signal.SIGTERM, signal.SIGKILL):
            live = await asyncio.to_thread(_descendants, proc.pid, self._owned)
            self._owned.update(live)
            for pid in live:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, sig)
            if live:
                await asyncio.sleep(0.4)
        if await asyncio.to_thread(_descendants, proc.pid, self._owned):
            raise T3Error("A process started by T3 is still running.")
        await proc.wait()
        await self._reader
        self._owned.clear()
        self._process = self._client = self._reader = self._watcher = None
