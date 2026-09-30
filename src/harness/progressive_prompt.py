"""Local directory context for R16 progressive prompting."""

from __future__ import annotations

import re
from pathlib import Path

from harness.project_path import project_environment
from harness.toolset import AgentLocation

_INSTRUCTION_NAMES = (
    "AGENTS.override.md",
    "AGENTS.md",
    "AGENTS.MD",
    "CLAUDE.md",
    "CLAUDE.MD",
)
_RENDERED_LOCATION = re.compile(
    r"<workspace_context>\nWorkspace root: [^\n]*\nCurrent location: ([^\n]+)\n"
)


def workspace_location_path(location: AgentLocation) -> str:
    """Return the one canonical workspace-relative directory for location scoring."""

    root = location.workspace_root.resolve(strict=True)
    cwd = location.cwd.resolve(strict=True)
    relative = cwd.relative_to(root)
    return "." if not relative.parts else relative.as_posix()


def render_workspace_context(location: AgentLocation) -> str:
    """Render CWD facts and root-to-location agent instructions."""

    root = location.workspace_root.resolve(strict=True)
    cwd = location.cwd.resolve(strict=True)
    relative = workspace_location_path(location)
    entries = _directory_entries(cwd)
    instruction_sections = _instruction_sections(root, cwd)
    environment = project_environment(cwd, root)
    lines = [
        "<workspace_context>",
        f"Workspace root: {root}",
        f"Current location: {cwd}",
        f"Workspace-relative location: {relative}",
        "Treat the workspace root as the hard file-operation boundary for this thread.",
        "To edit or write a file, first move to its exact directory. "
        "Shell commands write only within the current location's subtree, except git "
        "commands on this repository, which work from any folder inside it; reads are free. "
        "If a write is refused, move to the folder it needs instead of probing the sandbox.",
        # M3W5B-02/03: run the project's tools where you stand instead of moving to run them.
        *(
            ()
            if environment is None
            else (
                f"Project environment: {environment} comes first on the shell's PATH, so "
                "python, pytest and its other tools run from any folder here without moving.",
            )
        ),
        "Directory entries:",
        *(f"- {entry}" for entry in entries),
    ]
    if instruction_sections:
        lines.extend(
            ("Local agent instructions (root to current location):", *instruction_sections)
        )
    else:
        lines.append("Local agent instructions: none")
    lines.append("</workspace_context>")
    return "\n".join(lines)


def rendered_location(instructions: str | None) -> str | None:
    """SD-072: read back the current location a rendered workspace context gave the model."""

    match = None if instructions is None else _RENDERED_LOCATION.search(instructions)
    return None if match is None else match.group(1)


def _directory_entries(cwd: Path) -> tuple[str, ...]:
    try:
        children = sorted(cwd.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
    except OSError:
        return ("(unavailable)",)
    rendered = [f"{item.name}/" if item.is_dir() else item.name for item in children]
    return tuple(rendered) if rendered else ("(empty)",)


def _instruction_sections(root: Path, cwd: Path) -> tuple[str, ...]:
    directories = [root]
    if cwd != root:
        current = root
        for segment in cwd.relative_to(root).parts:
            current = current / segment
            directories.append(current)

    sections: list[str] = []
    for directory in directories:
        selected = next(
            (directory / name for name in _INSTRUCTION_NAMES if (directory / name).is_file()), None
        )
        if selected is None:
            continue
        try:
            resolved = selected.resolve(strict=True)
            # WALL credentials: ADR-015 keeps repository symlinks from importing outside files.
            if not resolved.is_relative_to(root):
                continue
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        label = resolved.relative_to(root).as_posix()
        sections.append(f"--- {label} ---\n{content}")
    return tuple(sections)


__all__ = ["render_workspace_context", "rendered_location", "workspace_location_path"]
