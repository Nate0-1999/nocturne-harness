"""The sole adapter from Nocturne's toolset seam to pydantic-ai-harness."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai_harness import Skills
from pydantic_ai_harness.filesystem import FileSystemToolset
from pydantic_ai_harness.shell import ShellToolset

from harness.toolset import (
    AgentLocation,
    PresenceEvent,
    PresenceSink,
    ToolExecutionResult,
    ToolName,
    ToolsetError,
)

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


def _clean_path(raw_path: object, *, default: str | None = None) -> str:
    if raw_path is None and default is not None:
        return default
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("path must be a nonblank string")
    cleaned = raw_path.strip()
    return cleaned[1:] if cleaned.startswith("@") else cleaned


def _skill_resources(package: Path) -> tuple[Path, ...]:
    root = package.resolve(strict=True)
    resources: list[Path] = []
    for candidate in sorted(package.rglob("*")):
        if candidate.name == "SKILL.md" or not candidate.is_file():
            continue
        resolved = candidate.resolve(strict=True)
        if _inside(root, resolved):
            resources.append(resolved)
    return tuple(resources)


def _resource_instructions(package: Path) -> str:
    resources = _skill_resources(package)
    if not resources:
        return ""
    root = package.resolve(strict=True)
    lines = [
        "## Bundled resources",
        "",
        f"This skill package is rooted at `{root}`.",
        "Use Nocturne's `read` tool to open only the resources the skill requires.",
        "Scripts are resources too: inspect them before running them through the fenced shell.",
        "",
        *[f"- `{resource.relative_to(root).as_posix()}`" for resource in resources],
    ]
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class AdoptedSkill:
    """Framework-neutral skill data returned across the ADR-013 import fence."""

    id: str
    description: str | None
    instructions: tuple[str, ...]


def adopted_skills(directories: Sequence[Path]) -> tuple[AdoptedSkill, ...]:
    """Adopt upstream deferred skills and add model-visible bundled resources."""

    libraries = tuple(path.resolve(strict=True) for path in directories if path.is_dir())
    if not libraries:
        return ()
    leaves: list[Any] = []
    Skills(libraries).apply(leaves.append)
    packages = {
        unicodedata.normalize("NFKC", child.name): child
        for library in libraries
        for child in sorted(library.iterdir())
        if child.is_dir() and (child / "SKILL.md").is_file()
    }
    adopted: list[AdoptedSkill] = []
    for leaf in leaves:
        package = packages[leaf.id]
        instructions = list(leaf.get_instructions() or ())
        resources = _resource_instructions(package)
        if resources:
            instructions.append(resources)
        adopted.append(
            AdoptedSkill(
                id=leaf.id,
                description=leaf.description,
                instructions=tuple(instructions),
            )
        )
    return tuple(adopted)


def discover_skill_libraries(workspace_root: Path) -> tuple[Path, ...]:
    """Return the explicit project and user libraries inherited from the PI layer."""

    candidates = (
        workspace_root / ".agents" / "skills",
        workspace_root / ".pi" / "skills",
        Path.home() / ".agents" / "skills",
        Path.home() / ".pi" / "agent" / "skills",
    )
    seen: set[Path] = set()
    libraries: list[Path] = []
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        resolved = candidate.resolve(strict=True)
        if resolved not in seen:
            seen.add(resolved)
            libraries.append(resolved)
    return tuple(libraries)


class PydanticHarnessToolset:
    """In-process implementation of Nocturne's owned standard-tool contract."""

    def __init__(
        self,
        *,
        location: AgentLocation,
        presence_sink: PresenceSink | None,
    ) -> None:
        self._location = location
        self._presence_sink = presence_sink
        self._presence_events: list[PresenceEvent] = []
        self._closed = False
        self._emit("spawn", location.cwd)

    @classmethod
    async def open(
        cls,
        *,
        cwd: Path | None = None,
        workspace_root: Path | None = None,
        agent_id: str = "harness-agent",
        machine_id: str = "local-machine",
        session_id: str,
        fence_reads: bool = False,
        presence_sink: PresenceSink | None = None,
    ) -> Self:
        for name, value in (
            ("agent_id", agent_id),
            ("machine_id", machine_id),
            ("session_id", session_id),
        ):
            if not value.strip() or "\n" in value or "\r" in value:
                raise ValueError(f"{name} must be nonblank and single-line")
        initial_location = (cwd or Path.cwd()).resolve(strict=True)
        root = (workspace_root or initial_location).resolve(strict=True)
        if not initial_location.is_dir() or not root.is_dir():
            raise ValueError("cwd and workspace_root must be existing directories")
        if not _inside(root, initial_location):
            raise ValueError("cwd must be inside workspace_root")
        return cls(
            location=AgentLocation(
                agent_id=agent_id,
                machine_id=machine_id,
                session_id=session_id,
                workspace_root=root,
                cwd=initial_location,
                fence_reads=fence_reads,
            ),
            presence_sink=presence_sink,
        )

    def location(self) -> AgentLocation:
        return self._location

    def presence_events(self) -> tuple[PresenceEvent, ...]:
        return tuple(self._presence_events)

    async def move(self, path: Path) -> AgentLocation:
        self._require_open()
        target = path if path.is_absolute() else self._location.cwd / path
        target = target.resolve(strict=True)
        if not target.is_dir():
            raise ValueError(f"Cannot move to {target}: not a directory.")
        if not _inside(self._location.workspace_root, target):
            raise ValueError(f"Cannot move outside the workspace {self._location.workspace_root}.")
        self._location = AgentLocation(
            agent_id=self._location.agent_id,
            machine_id=self._location.machine_id,
            session_id=self._location.session_id,
            workspace_root=self._location.workspace_root,
            cwd=target,
            fence_reads=self._location.fence_reads,
        )
        self._emit("cwd_change", target)
        return self._location

    async def execute(
        self,
        tool_name: ToolName,
        arguments: Mapping[str, object],
    ) -> ToolExecutionResult:
        self._require_open()
        try:
            if tool_name == "move":
                location = await self.move(Path(_clean_path(arguments.get("path"))))
                content = f"Moved to {location.cwd}."
            elif tool_name == "bash":
                content = await self._bash(arguments)
            elif tool_name == "read":
                content = await self._read(arguments)
            elif tool_name == "write":
                content = await self._write(arguments)
            elif tool_name == "edit":
                content = await self._edit(arguments)
            elif tool_name == "grep":
                content = await self._grep(arguments)
            elif tool_name == "find":
                content = await self._find(arguments)
            elif tool_name == "ls":
                content = await self._ls(arguments)
            else:
                raise ValueError(f"unsupported standard tool: {tool_name}")
        except (ToolsetError, ModelRetry, OSError, ValueError) as exc:
            return ToolExecutionResult(tool_name=tool_name, content=str(exc), success=False)
        return ToolExecutionResult(tool_name=tool_name, content=content, success=True)

    async def close(self) -> None:
        if self._closed:
            return
        self._emit("exit", self._location.cwd)
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise ToolsetError("The workspace toolset is closed.")

    def _emit(self, event: str, path: Path) -> None:
        record = PresenceEvent(
            agent_id=self._location.agent_id,
            machine_id=self._location.machine_id,
            session_id=self._location.session_id,
            event=event,  # type: ignore[arg-type]
            path=path,
            ts=datetime.now(UTC),
        )
        self._presence_events.append(record)
        if self._presence_sink is not None:
            self._presence_sink(record)

    def _target(self, raw_path: object, *, default: str | None = None) -> Path:
        supplied = Path(_clean_path(raw_path, default=default))
        return (supplied if supplied.is_absolute() else self._location.cwd / supplied).resolve(
            strict=False
        )

    def _preflight(self, tool_name: str, raw_path: object, *, default: str | None = None) -> Path:
        target = self._target(raw_path, default=default)
        if tool_name in _READ_TOOLS and _credential_path(target):
            raise ToolsetError(
                "That path may contain credentials. Ask the owner before reading it."
            )
        if tool_name in _WRITE_TOOLS and target.parent != self._location.cwd:
            raise ToolsetError(
                "Modification requires presence in the file's directory. "
                f"Move to {target.parent} first."
            )
        if (
            self._location.fence_reads
            and tool_name in _READ_TOOLS
            and not _inside(self._location.cwd, target)
        ):
            raise ToolsetError(
                f"That path is outside this agent's location. Move to {target} first."
            )
        return target

    @staticmethod
    def _filesystem(
        root: Path,
        *,
        list_limit: int = 1000,
        search_limit: int = 1000,
        find_limit: int = 1000,
    ) -> FileSystemToolset[Any]:
        return FileSystemToolset(
            root_dir=root,
            allowed_patterns=[],
            denied_patterns=[],
            protected_patterns=[],
            max_read_lines=2000,
            max_list_results=list_limit,
            max_search_results=search_limit,
            max_find_results=find_limit,
        )

    async def _read(self, arguments: Mapping[str, object]) -> str:
        target = self._preflight("read", arguments.get("path"))
        offset = arguments.get("offset", 1)
        limit = arguments.get("limit", 2000)
        if not isinstance(offset, int) or offset < 1:
            raise ValueError("offset must be a positive one-indexed line number")
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be positive")
        result = await self._filesystem(target.parent).read_file(
            target.name, offset=offset - 1, limit=limit
        )
        self._emit("read", target)
        return result

    async def _write(self, arguments: Mapping[str, object]) -> str:
        target = self._preflight("write", arguments.get("path"))
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        relative = target.relative_to(self._location.cwd)
        result = await self._filesystem(self._location.cwd).write_file(str(relative), content)
        self._emit("write", target)
        return result

    async def _edit(self, arguments: Mapping[str, object]) -> str:
        target = self._preflight("edit", arguments.get("path"))
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
                raise ToolsetError(
                    f"oldText found {count} times; each replacement must be unique "
                    "in the original file"
                )
            start = original.index(old_text)
            spans.append((start, start + len(old_text), new_text))
        ordered = sorted(spans)
        if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:], strict=False)):
            raise ToolsetError("edit replacements overlap in the original file")
        revised = original
        for start, end, replacement in reversed(ordered):
            revised = revised[:start] + replacement + revised[end:]
        expected_hash = hashlib.sha256(original.encode()).hexdigest()[:12]
        relative = target.relative_to(self._location.cwd)
        result = await self._filesystem(self._location.cwd).edit_file(
            str(relative), original, revised, expected_hash=expected_hash
        )
        self._emit("write", target)
        return result

    async def _grep(self, arguments: Mapping[str, object]) -> str:
        target = self._preflight("grep", arguments.get("path"), default=".")
        if not target.is_dir():
            raise ValueError("grep path must be a directory")
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
        context = arguments.get("context", 0)
        limit = arguments.get("limit", 100)
        if not isinstance(context, int) or context < 0:
            raise ValueError("context must be a nonnegative integer")
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be positive")
        filesystem = self._filesystem(target, search_limit=limit)
        matches = await filesystem.search_files(pattern, path=".", include_glob=glob)
        self._emit("read", target)
        if context == 0 or not matches or matches.startswith("["):
            return matches
        return await self._grep_context(filesystem, matches, context)

    @staticmethod
    async def _grep_context(filesystem: FileSystemToolset[Any], matches: str, context: int) -> str:
        intervals: dict[str, list[tuple[int, int]]] = {}
        for line in matches.splitlines():
            try:
                path, raw_line, _ = line.rsplit(":", 2)
                line_number = int(raw_line)
            except (ValueError, TypeError):
                continue
            intervals.setdefault(path, []).append(
                (max(1, line_number - context), line_number + context)
            )
        blocks: list[str] = []
        for path, ranges in intervals.items():
            merged: list[list[int]] = []
            for start, end in sorted(ranges):
                if merged and start <= merged[-1][1] + 1:
                    merged[-1][1] = max(merged[-1][1], end)
                else:
                    merged.append([start, end])
            for start, end in merged:
                blocks.append(
                    await filesystem.read_file(path, offset=start - 1, limit=end - start + 1)
                )
        return "\n--\n".join(blocks) if blocks else matches

    async def _find(self, arguments: Mapping[str, object]) -> str:
        target = self._preflight("find", arguments.get("path"), default=".")
        if not target.is_dir():
            raise ValueError("find path must be a directory")
        pattern = arguments.get("pattern")
        limit = arguments.get("limit", 1000)
        if not isinstance(pattern, str) or not isinstance(limit, int) or limit < 1:
            raise ValueError("find requires a string pattern and positive limit")
        result = await self._filesystem(target, find_limit=limit).find_files(pattern, path=".")
        self._emit("read", target)
        return result

    async def _ls(self, arguments: Mapping[str, object]) -> str:
        target = self._preflight("ls", arguments.get("path"), default=".")
        if not target.is_dir():
            raise ValueError("ls path must be a directory")
        limit = arguments.get("limit", 500)
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be positive")
        result = await self._filesystem(target, list_limit=limit).list_directory(".")
        self._emit("read", target)
        return result

    async def _bash(self, arguments: Mapping[str, object]) -> str:
        command = arguments.get("command")
        timeout = arguments.get("timeout")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a nonblank string")
        if timeout is not None and not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be numeric")
        if _BOUNDARY_COMMAND.search(command):
            raise ToolsetError(
                "That command may leave this project or change remote state. "
                "Ask the owner to run it explicitly outside Nocturne."
            )
        if _CREDENTIAL_COMMAND.search(command):
            raise ToolsetError(
                "That command may expose credentials. Ask the owner before reading them."
            )
        sandbox = Path("/usr/bin/sandbox-exec")
        if not sandbox.is_file():
            raise ToolsetError(
                "Secure shell is unavailable on this host; use read, edit, and write instead."
            )
        quoted_location = json.dumps(str(self._location.cwd))
        profile = (
            "(version 1) (deny default) (allow process*) (allow file-read*) "
            "(allow sysctl-read) (allow mach-lookup) "
            f"(allow file-write* (literal {quoted_location}) (subpath {quoted_location}) "
            '(literal "/dev/null"))'
        )
        wrapped = f"{sandbox} -p {shlex.quote(profile)} /bin/zsh -lc {shlex.quote(command)}"
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "TMPDIR": str(self._location.cwd),
            "NO_COLOR": os.environ.get("NO_COLOR", "1"),
        }
        for optional in ("LC_ALL", "TERM"):
            if value := os.environ.get(optional):
                environment[optional] = value
        shell = ShellToolset(
            cwd=self._location.cwd,
            allowed_commands=[],
            denied_commands=[],
            denied_operators=[],
            default_timeout=2_147_483.0,
            max_output_chars=200_000,
            persist_cwd=False,
            allow_interactive=False,
            env=environment,
        )
        try:
            result = await shell.run_command(
                wrapped, timeout_seconds=float(timeout) if timeout is not None else None
            )
        finally:
            await shell.__aexit__()
        self._emit("write", self._location.cwd)
        return result
