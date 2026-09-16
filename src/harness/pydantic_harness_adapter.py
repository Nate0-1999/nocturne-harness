"""The sole adapter from Nocturne's toolset seam to pydantic-ai-harness."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai_harness import Skills
from pydantic_ai_harness.compaction import (
    SlidingWindowCompaction,
    SummarizingCompaction,
    TieredCompaction,
    compact_now,
    estimate_context_tokens,
    estimate_token_count,
    reinject_pinned,
    resolve_context_window,
)
from pydantic_ai_harness.compaction._receipts import is_receipt_part
from pydantic_ai_harness.compaction._shared import find_safe_cutoff
from pydantic_ai_harness.compaction._summarizing_compaction import (
    _DEFAULT_SUMMARY_PROMPT as COMPACTION_SUMMARY_PROMPT,
)
from pydantic_ai_harness.compaction._summarizing_compaction import _format_messages
from pydantic_ai_harness.filesystem import FileSystemToolset
from pydantic_ai_harness.shell import ShellToolset
from pydantic_core import to_jsonable_python
from spine.tokens import cl100k_token_count

from harness.envelope import generate_ulid
from harness.spine_client import SpineClientError
from harness.toolset import (
    AgentLocation,
    PresenceEvent,
    PresenceSink,
    ToolExecutionResult,
    ToolName,
    ToolsetError,
    WorkspaceBoundaryError,
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
        "Use these absolute paths verbatim; relative paths resolve from the agent's location.",
        "Scripts are resources too: inspect them before running them through the fenced shell.",
        "",
        *[f"- `{resource}`" for resource in resources],
    ]
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class AdoptedSkill:
    """Framework-neutral skill data returned across the ADR-013 import fence."""

    id: str
    description: str | None
    instructions: tuple[str, ...]
    source: str
    version: str


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
        digest = hashlib.sha256((package / "SKILL.md").read_bytes())
        for resource in _skill_resources(package):
            digest.update(str(resource.relative_to(package.resolve())).encode())
            digest.update(b"\0")
            digest.update(resource.read_bytes())
        adopted.append(
            AdoptedSkill(
                id=leaf.id,
                description=leaf.description,
                instructions=tuple(instructions),
                source=str(package.resolve()),
                version="sha256:" + digest.hexdigest(),
            )
        )
    return tuple(adopted)


def discover_skill_libraries(
    workspace_root: Path,
    current_location: Path | None = None,
) -> tuple[Path, ...]:
    """Discover libraries from the thread root through its current location. [PLAN M3SK]"""

    locations = [workspace_root]
    if current_location is not None:
        for part in current_location.relative_to(workspace_root).parts:
            locations.append(locations[-1] / part)
    candidates = (
        *(location / folder / "skills" for location in locations for folder in (".agents", ".pi")),
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
        self._background_shells: dict[str, ShellToolset] = {}
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
        initial_location = (cwd or Path.cwd()).resolve(strict=True)
        root = (workspace_root or initial_location).resolve(strict=True)
        if not _inside(root, initial_location):
            # WALL owner files / ADR015: initial presence cannot exceed the granted workspace.
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
        if not _inside(self._location.workspace_root, target):
            # WALL owner files / ADR015: movement cannot enlarge the write grant.
            raise WorkspaceBoundaryError(
                f"Cannot move outside the workspace {self._location.workspace_root}.", "workspace"
            )
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
            else:
                content = await {
                    "bash": self._bash,
                    "start_shell": self._start_shell,
                    "read_shell": self._read_shell,
                    "stop_shell": self._stop_shell,
                    "read": self._read,
                    "write": self._write,
                    "edit": self._edit,
                    "grep": self._grep,
                    "find": self._find,
                    "ls": self._ls,
                }[tool_name](arguments)
        except WorkspaceBoundaryError as exc:
            return ToolExecutionResult(
                tool_name=tool_name, content=str(exc), success=False, boundary=exc.wall
            )
        except (ToolsetError, ModelRetry, OSError, ValueError) as exc:
            return ToolExecutionResult(tool_name=tool_name, content=str(exc), success=False)
        return ToolExecutionResult(tool_name=tool_name, content=content, success=True)

    async def close(self) -> None:
        if self._closed:
            return
        for shell in self._background_shells.values():
            await shell.__aexit__()
        self._background_shells.clear()
        self._emit("exit", self._location.cwd)
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            # WALL owner files / ADR015: writes require a live presence session.
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
            # WALL credentials / ADR015: do not expose credential files through reads.
            raise WorkspaceBoundaryError(
                "That path may contain credentials. Ask the owner before reading it.", "credentials"
            )
        if tool_name in _WRITE_TOOLS and not _inside(self._location.workspace_root, target):
            # WALL owner files / F083: route outside-workspace writes to the Deck.
            raise WorkspaceBoundaryError(
                f"That path is outside this workspace: {target}.", "workspace"
            )
        if tool_name in _WRITE_TOOLS and target.parent != self._location.cwd:
            # WALL owner files / ADR015: require presence in the exact directory being written.
            raise ToolsetError(
                "Modification requires presence in the file's directory. "
                f"Move to {target.parent} first."
            )
        if (
            self._location.fence_reads
            and tool_name in _READ_TOOLS
            and not _inside(self._location.cwd, target)
        ):
            # WALL owner files / ADR015: honor the delegated read boundary.
            raise WorkspaceBoundaryError(
                f"That path is outside this agent's location. Move to {target} first.", "location"
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
        # WALL money / ADR015: page tool output before it becomes paid model context.
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
        result = await self._filesystem(target.parent).read_file(
            target.name, offset=offset - 1, limit=limit
        )
        self._emit("read", target)
        return result

    async def _write(self, arguments: Mapping[str, object]) -> str:
        target = self._preflight("write", arguments.get("path"))
        content = arguments.get("content")
        relative = target.relative_to(self._location.cwd)
        result = await self._filesystem(self._location.cwd).write_file(str(relative), content)
        self._emit("write", target)
        return result

    async def _edit(self, arguments: Mapping[str, object]) -> str:
        target = self._preflight("edit", arguments.get("path"))
        edits = arguments.get("edits")
        original = target.read_text(encoding="utf-8")
        spans: list[tuple[int, int, str]] = []
        for item in edits:
            old_text = item.get("oldText")
            new_text = item.get("newText")
            if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
                # WALL owner files / ADR015: an empty search would replace unspecified file bytes.
                raise ValueError("each edit requires nonblank oldText and string newText")
            count = original.count(old_text)
            if count != 1:
                # WALL owner files / ADR015: do not guess which occurrence the model meant to edit.
                raise ToolsetError(
                    f"oldText found {count} times; each replacement must be unique "
                    "in the original file"
                )
            start = original.index(old_text)
            spans.append((start, start + len(old_text), new_text))
        ordered = sorted(spans)
        if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:], strict=False)):
            # WALL owner files / ADR015: overlapping replacements would corrupt file bytes.
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
        pattern = arguments.get("pattern")
        if arguments.get("literal", False):
            pattern = re.escape(pattern)
        if arguments.get("ignoreCase", False):
            pattern = f"(?i:{pattern})"
        glob = arguments.get("glob")
        context = arguments.get("context", 0)
        limit = arguments.get("limit", 100)
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
        pattern = arguments.get("pattern")
        limit = arguments.get("limit", 1000)
        result = await self._filesystem(target, find_limit=limit).find_files(pattern, path=".")
        self._emit("read", target)
        return result

    async def _ls(self, arguments: Mapping[str, object]) -> str:
        target = self._preflight("ls", arguments.get("path"), default=".")
        limit = arguments.get("limit", 500)
        result = await self._filesystem(target, list_limit=limit).list_directory(".")
        self._emit("read", target)
        return result

    async def _bash(self, arguments: Mapping[str, object]) -> str:
        shell, wrapped = self._shell_command(arguments)
        timeout = arguments.get("timeout")
        try:
            result = await shell.run_command(
                wrapped, timeout_seconds=float(timeout) if timeout is not None else None
            )
        finally:
            await shell.__aexit__()
        self._emit("write", self._location.cwd)
        return result

    async def _start_shell(self, arguments: Mapping[str, object]) -> str:
        shell, wrapped = self._shell_command(arguments)
        try:
            result = await shell.start_command(wrapped)
        except BaseException:
            await shell.__aexit__()
            raise
        if "\nID: " not in result:
            await shell.__aexit__()
            # A-069: retain only a successfully launched upstream process handle.
            raise ToolsetError(result)
        command_id = result.rsplit("ID: ", 1)[1].strip()
        self._background_shells[command_id] = shell
        self._emit("write", self._location.cwd)
        return f"Started background shell. ID: {command_id}. Use read_shell or stop_shell."

    async def _read_shell(self, arguments: Mapping[str, object]) -> str:
        command_id = str(arguments.get("command_id", ""))
        shell = self._background_shells.get(command_id)
        if shell is None:
            # A-069: a shell handle belongs to its originating thread.
            raise ToolsetError("No background shell with that ID in this thread.")
        return await shell.check_command(command_id)

    async def _stop_shell(self, arguments: Mapping[str, object]) -> str:
        command_id = str(arguments.get("command_id", ""))
        shell = self._background_shells.get(command_id)
        if shell is None:
            # A-069: stopping a shell requires this thread's retained handle.
            raise ToolsetError("No background shell with that ID in this thread.")
        return await shell.stop_command(command_id)

    def _shell_command(self, arguments: Mapping[str, object]) -> tuple[ShellToolset, str]:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            # A-069: the saved or interactive shell must name actual work.
            raise ToolsetError("A shell command is required.")
        if _BOUNDARY_COMMAND.search(command):
            # WALL owner files / ADR015: shell tools cannot publish or escape the project grant.
            raise WorkspaceBoundaryError(
                "That command may leave this project or change remote state. "
                "Ask the owner to run it explicitly outside Nocturne.",
                "remote",
            )
        if _CREDENTIAL_COMMAND.search(command):
            # WALL credentials / ADR015: shell output must not read credential stores.
            raise WorkspaceBoundaryError(
                "That command may expose credentials. Ask the owner before reading them.",
                "credentials",
            )
        sandbox = Path("/usr/bin/sandbox-exec")
        if not sandbox.is_file():
            # WALL owner files / ADR015: never run an unfenced shell when sandboxing is absent.
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
            default_timeout=2_147_483.0,  # WALL money / ADR-015: launched process lifetime.
            max_output_chars=200_000,  # WALL money / F034: tool output enters paid context.
            persist_cwd=False,
            allow_interactive=False,
            env=environment,
        )
        return shell, wrapped


def own_history(messages):
    """D.2 153: worker returns do not contribute to the main thread's fill."""
    return [
        replace(
            message,
            parts=[
                part
                for part in message.parts
                if not isinstance(part, ToolReturnPart) or part.tool_name != "delegate_task"
            ],
        )
        if isinstance(message, ModelRequest)
        else message
        for message in messages
    ]


class CompactionPolicy(BaseModel):
    """Per-thread strategy and model-portable fill policy, persisted in the journal."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    strategy: Literal["truncate", "summarize", "memories-then-drop", "human-and-final-only"] = (
        "memories-then-drop"
    )
    policy: Literal["performance", "cost"] = "performance"
    # D.2 153: the trigger is a finite fraction of the active model's window.
    fraction: float = Field(default=0.8, gt=0, lt=1, allow_inf_nan=False)
    instructions: str = COMPACTION_SUMMARY_PROMPT


class _HumanFinalCompaction(SlidingWindowCompaction):
    """Our drop strategy in the package slot; pins, pair safety and receipts are upstream."""

    async def compact(self, messages, ctx):
        # Keep the in-flight tool exchange intact, as well as the last final answer.
        cutoff = find_safe_cutoff(messages, 1)
        final = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, ModelResponse)
                and any(isinstance(part, TextPart) for part in message.parts)
                and not any(isinstance(part, ToolCallPart) for part in message.parts)
            ),
            None,
        )
        retained = []
        for index, message in enumerate(messages):
            if index >= cutoff or message is final:
                retained.append(message)
            elif isinstance(message, ModelRequest):
                parts = [
                    part
                    for part in message.parts
                    if isinstance(part, (UserPromptPart, SystemPromptPart))
                    and not is_receipt_part(part)
                ]
                if parts:
                    retained.append(
                        message if parts == message.parts else replace(message, parts=parts)
                    )
        retained = reinject_pinned(messages, retained)
        if self._without_receipts(retained) == self._without_receipts(messages):
            return messages
        retained = self._without_receipts(retained)
        return [self._receipt_message(self._dropped_messages(messages, retained), ctx), *retained]


class _PreparedSummary(SummarizingCompaction):
    summary: str = ""

    async def _summarize(self, messages, ctx, *, previous_summary=None):
        return self.summary


class _MemoryStrategy:
    def __init__(self, owner):
        self.owner = owner

    async def compact(self, messages, ctx):
        owner = self.owner
        if owner.completed:
            return messages
        window = owner.context_window or resolve_context_window(ctx.model) or 200_000
        options = dict(
            max_messages=1,
            keep_tokens=max(1, window // 5),
            tokenizer=cl100k_token_count,
            receipts=True,
            preserve_first_user_message=False,
        )
        strategy = owner.policy.strategy
        engine = (
            _PreparedSummary(**options)
            if strategy == "summarize"
            else SlidingWindowCompaction(**options)
            if strategy == "truncate"
            else _HumanFinalCompaction(**options)
        )
        # A no-op must not manufacture extraction events on every subsequent tool step.
        if strategy != "summarize":
            proposed = await engine.compact(messages, ctx)
            if proposed == messages:
                return messages
        before = estimate_context_tokens(messages, cl100k_token_count)
        owner.original_history = list(messages)
        await owner.emit.event(
            {"event_kind": "compaction_started", "before_tokens": before, "strategy": strategy}
        )
        result = await owner.service.triage(
            ctx.deps.thread_id,
            _format_messages(own_history(messages)),
            tail=owner.emit.run_id,
            origin="compaction",
            model=ctx.model,
            usage=ctx.usage,
            on_result=owner.on_result,
            model_settings=owner.model_settings,
            summary_prompt=owner.policy.instructions,
        )
        # Admission must finish before any drop; a failed queue write leaves history intact.
        if strategy == "summarize":
            engine.summary = result.working_summary + "\n\n" + "\n".join(result.open_loops)
            proposed = await engine.compact(messages, ctx)
        if proposed == messages:
            return messages
        owner.completed = True
        owner.history = proposed
        event_uid = generate_ulid()
        owner.service._journal.append_compaction_history(
            str(ctx.deps.thread_id),
            owner.emit.run_id,
            to_jsonable_python(proposed),
        )
        await owner.emit.event(
            {
                "event_kind": "compaction_memories",
                "candidate_count": len(result.cards),
                "working_summary": result.working_summary,
                "open_loops": result.open_loops,
            }
        )
        await owner.emit.event(
            {
                "event_kind": "compaction_completed",
                "before_tokens": before,
                "after_tokens": estimate_token_count(proposed, cl100k_token_count),
                "event_uid": event_uid,
                "strategy": strategy,
            }
        )
        try:
            await owner.service._spine.notify_compaction(event_uid, ctx.deps.thread_id)
        except SpineClientError:
            await owner.emit.event(
                {
                    "event_kind": "compaction_optimizer_unavailable",
                    "message": "History compacted; the Palace could not start optimization.",
                }
            )
        return proposed


class MemoryCompaction(TieredCompaction):
    """Upstream escalation/usage accounting with our queue-before-drop strategy."""

    def __init__(
        self, service, emit, window=None, on_result=None, *, policy=None, model_settings=None
    ):
        self.policy = policy or CompactionPolicy()
        self.service, self.emit, self.on_result = service, emit, on_result
        self.model_settings = model_settings
        self.completed = False
        self.history = []
        self.original_history = []
        super().__init__(
            tiers=[_MemoryStrategy(self)],
            target_fraction=self.policy.fraction,
            context_window=window,
            tokenizer=cl100k_token_count,
        )

    def compaction_transcript_handle(self):
        return self.emit.run_id

    async def before_model_request(self, ctx, request_context):
        messages = request_context.messages
        worker_tokens = estimate_token_count(messages, self.tokenizer) - estimate_token_count(
            own_history(messages),
            self.tokenizer,
        )
        # D.2 153: worker bulk cannot cause the main thread's entropy event.
        own_tokens = (
            estimate_context_tokens(
                messages,
                self.tokenizer,
                model_request_parameters=request_context.model_request_parameters,
            )
            - worker_tokens
        )
        target = self._target(request_context.model)
        if target is None or own_tokens <= target:
            return request_context
        return await super().before_model_request(ctx, request_context)

    async def manual(self, messages, *, model, deps, usage):
        return await compact_now(
            self.tiers[0],
            list(messages),
            model=model,
            deps=deps,
            usage=usage,
            tokenizer=self.tokenizer,
        )
