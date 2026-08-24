"""M3PV disposable prototype for an in-process pydantic-ai-harness tool layer.

This is verification evidence, not product code.  It intentionally keeps the
NOCTURNE-owned seven-tool names and location policy while delegating commodity
file and shell behavior to pydantic-ai-harness 0.24.0.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Callable, Mapping
from pathlib import Path

from pydantic_ai_harness.filesystem import FileSystemToolset
from pydantic_ai_harness.shell import ShellToolset


class FenceRefusal(RuntimeError):
    """The requested act crosses a NOCTURNE-owned boundary."""


class CoverageGap(RuntimeError):
    """The released candidate cannot preserve one required behavior."""


_READ_TOOLS = frozenset({"read", "grep", "find", "ls"})
_WRITE_TOOLS = frozenset({"edit", "write"})
_BOUNDARY_COMMAND = re.compile(
    r"\b(?:git\s+push|gh\s+(?:pr|release)|gcloud|aws|az|kubectl|"
    r"terraform\s+(?:apply|destroy)|curl|wget|ssh|scp|rsync)\b",
    re.IGNORECASE,
)
_CREDENTIAL_COMMAND = re.compile(
    r"(?:^|[\s/])(?:\.env(?:\.[^\s/]*)?|\.ssh|\.aws|\.gnupg|\.kube|"
    r"id_rsa|id_ed25519)(?:[\s/]|$)|^\s*(?:env|printenv|set)\s*$",
    re.IGNORECASE,
)
_CREDENTIAL_SEGMENTS = frozenset({".ssh", ".aws", ".gnupg", ".kube"})


def _inside(root: Path, target: Path) -> bool:
    return target == root or target.is_relative_to(root)


def _credential_path(target: Path) -> bool:
    lowered = [part.lower() for part in target.parts]
    name = target.name.lower()
    return (
        any(part in _CREDENTIAL_SEGMENTS for part in lowered)
        or name == ".env"
        or name.startswith(".env.")
        or bool(re.fullmatch(r"id_rsa|id_ed25519|credentials|service-account.*\.json", name))
        or any(
            part == ".config" and index + 1 < len(lowered) and lowered[index + 1] == "gcloud"
            for index, part in enumerate(lowered)
        )
    )


class CandidateFencedWrapper:
    """Small owned adapter around the released official capability toolsets."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        cwd: Path,
        fence_reads: bool = False,
        movement_refresh: Callable[[Path], None] | None = None,
    ) -> None:
        root = workspace_root.resolve(strict=True)
        location = cwd.resolve(strict=True)
        if not root.is_dir() or not location.is_dir() or not _inside(root, location):
            raise ValueError("cwd must be an existing directory inside workspace_root")
        self.workspace_root = root
        self.cwd = location
        self.fence_reads = fence_reads
        self._movement_refresh = movement_refresh
        self.events: list[tuple[str, Path]] = [("spawn", location)]

    def _target(self, raw_path: object) -> Path:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("path must be a nonblank string")
        cleaned = raw_path.strip()
        if cleaned.startswith("@"):
            cleaned = cleaned[1:]
        supplied = Path(cleaned)
        return (supplied if supplied.is_absolute() else self.cwd / supplied).resolve(strict=False)

    def _preflight_path(self, tool_name: str, raw_path: object) -> Path:
        target = self._target(raw_path)
        if tool_name in _READ_TOOLS and _credential_path(target):
            raise FenceRefusal(
                "That path may contain credentials. Ask the owner before reading it."
            )
        fenced = tool_name in _WRITE_TOOLS or self.fence_reads
        if fenced and not _inside(self.cwd, target):
            remedy = target.parent if tool_name in _WRITE_TOOLS else target
            raise FenceRefusal(
                f"That path is outside this agent's location. Move to {remedy} first."
            )
        return target

    def _filesystem(
        self,
        *,
        list_limit: int = 1000,
        search_limit: int = 1000,
        find_limit: int = 1000,
    ) -> FileSystemToolset[object]:
        # Reads are intentionally free beyond the current location.  Rooting the
        # adopted containment layer at the host volume preserves that law while
        # the owned preflight above supplies the narrower write fence.
        volume_root = Path(self.workspace_root.anchor).resolve(strict=True)
        return FileSystemToolset(
            root_dir=volume_root,
            allowed_patterns=[],
            denied_patterns=[],
            protected_patterns=[],
            max_read_lines=2000,
            max_list_results=list_limit,
            max_search_results=search_limit,
            max_find_results=find_limit,
        )

    async def move(self, raw_path: object) -> Path:
        target = self._target(raw_path)
        if not target.is_dir():
            raise FenceRefusal(f"Cannot move to {target}: not a directory.")
        if not _inside(self.workspace_root, target):
            raise FenceRefusal(f"Cannot move outside the workspace {self.workspace_root}.")
        self.cwd = target
        self.events.append(("cwd_change", target))
        if self._movement_refresh is not None:
            self._movement_refresh(target)
        return target

    async def execute(self, tool_name: str, arguments: Mapping[str, object]) -> str:
        if tool_name == "move":
            return f"Moved to {await self.move(arguments.get('path'))}."
        if tool_name == "bash":
            return await self._bash(arguments)
        if tool_name not in _READ_TOOLS | _WRITE_TOOLS:
            raise ValueError(f"unsupported tool: {tool_name}")

        if tool_name == "read":
            target = self._preflight_path(tool_name, arguments.get("path"))
            offset = arguments.get("offset", 1)
            limit = arguments.get("limit", 2000)
            if not isinstance(offset, int) or offset < 1:
                raise ValueError("offset must be a positive one-indexed line number")
            if not isinstance(limit, int) or limit < 1:
                raise ValueError("limit must be positive")
            result = await self._filesystem().read_file(str(target), offset=offset - 1, limit=limit)
        elif tool_name == "write":
            target = self._preflight_path(tool_name, arguments.get("path"))
            content = arguments.get("content")
            if not isinstance(content, str):
                raise ValueError("content must be a string")
            result = await self._filesystem().write_file(str(target), content)
        elif tool_name == "edit":
            result = await self._edit(arguments)
            target = self._target(arguments.get("path"))
        elif tool_name == "grep":
            target = self._preflight_path(tool_name, arguments.get("path", "."))
            context = arguments.get("context", 0)
            if context != 0:
                raise CoverageGap(
                    "pydantic-ai-harness 0.24.0 search_files has no context-line behavior"
                )
            pattern = arguments.get("pattern")
            if not isinstance(pattern, str):
                raise ValueError("pattern must be a string")
            if arguments.get("literal", False):
                pattern = re.escape(pattern)
            if arguments.get("ignoreCase", False):
                pattern = f"(?i:{pattern})"
            glob = arguments.get("glob")
            if glob is not None and not isinstance(glob, str):
                raise ValueError("glob must be a string")
            limit = arguments.get("limit", 100)
            if not isinstance(limit, int) or limit < 1:
                raise ValueError("limit must be positive")
            result = await self._filesystem(search_limit=limit).search_files(
                pattern, path=str(target), include_glob=glob
            )
        elif tool_name == "find":
            target = self._preflight_path(tool_name, arguments.get("path", "."))
            pattern = arguments.get("pattern")
            limit = arguments.get("limit", 1000)
            if not isinstance(pattern, str) or not isinstance(limit, int) or limit < 1:
                raise ValueError("find requires a string pattern and positive limit")
            result = await self._filesystem(find_limit=limit).find_files(pattern, path=str(target))
        else:
            target = self._preflight_path(tool_name, arguments.get("path", "."))
            limit = arguments.get("limit", 500)
            if not isinstance(limit, int) or limit < 1:
                raise ValueError("limit must be positive")
            result = await self._filesystem(list_limit=limit).list_directory(str(target))

        self.events.append(("write" if tool_name in _WRITE_TOOLS else "read", target))
        return result

    async def _edit(self, arguments: Mapping[str, object]) -> str:
        target = self._preflight_path("edit", arguments.get("path"))
        edits = arguments.get("edits")
        if not isinstance(edits, list) or not edits:
            raise ValueError("edits must be a nonempty list")
        original = target.read_text(encoding="utf-8")
        spans: list[tuple[int, int, str]] = []
        for item in edits:
            if not isinstance(item, Mapping):
                raise ValueError("each edit must be a mapping")
            old_text = item.get("oldText")
            new_text = item.get("newText")
            if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
                raise ValueError("each edit requires nonblank oldText and string newText")
            count = original.count(old_text)
            if count != 1:
                raise FenceRefusal(
                    f"oldText found {count} times; each replacement must be unique "
                    "in the original file"
                )
            start = original.index(old_text)
            spans.append((start, start + len(old_text), new_text))
        ordered = sorted(spans)
        if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:], strict=False)):
            raise FenceRefusal("edit replacements overlap in the original file")
        revised = original
        for start, end, replacement in reversed(ordered):
            revised = revised[:start] + replacement + revised[end:]
        expected_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()[:12]
        return await self._filesystem().edit_file(
            str(target), original, revised, expected_hash=expected_hash
        )

    async def _bash(self, arguments: Mapping[str, object]) -> str:
        command = arguments.get("command")
        timeout = arguments.get("timeout")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a nonblank string")
        if timeout is not None and not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be numeric")
        if _BOUNDARY_COMMAND.search(command):
            raise FenceRefusal(
                "That command may leave this project or change remote state. "
                "Ask the owner to run it explicitly outside Nocturne."
            )
        if _CREDENTIAL_COMMAND.search(command):
            raise FenceRefusal(
                "That command may expose credentials. Ask the owner before reading them."
            )
        if not Path("/usr/bin/sandbox-exec").is_file():
            raise CoverageGap("the current hard bash fence requires macOS sandbox-exec")

        quoted_location = json.dumps(str(self.cwd))
        profile = (
            "(version 1) (deny default) (allow process*) (allow file-read*) "
            "(allow sysctl-read) (allow mach-lookup) "
            f"(allow file-write* (literal {quoted_location}) (subpath {quoted_location}) "
            '(literal "/dev/null"))'
        )
        wrapped = (
            f"/usr/bin/sandbox-exec -p {shlex.quote(profile)} /bin/zsh -lc {shlex.quote(command)}"
        )
        shell = ShellToolset(
            cwd=self.cwd,
            allowed_commands=[],
            denied_commands=[],
            denied_operators=[],
            default_timeout=2_147_483.0,
            max_output_chars=200_000,
            persist_cwd=False,
            allow_interactive=False,
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "LANG": "en_US.UTF-8",
                "TMPDIR": str(self.cwd),
                "NO_COLOR": "1",
            },
        )
        try:
            result = await shell.run_command(
                wrapped, timeout_seconds=float(timeout) if timeout is not None else None
            )
        finally:
            await shell.__aexit__()
        self.events.append(("write", self.cwd))
        return result
