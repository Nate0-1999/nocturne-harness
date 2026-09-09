"""Local directory context for R16 progressive prompting."""

from __future__ import annotations

from pathlib import Path

from harness.toolset import AgentLocation

_INSTRUCTION_NAMES = (
    "AGENTS.override.md",
    "AGENTS.md",
    "AGENTS.MD",
    "CLAUDE.md",
    "CLAUDE.MD",
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
    lines = [
        "<workspace_context>",
        f"Workspace root: {root}",
        f"Current location: {cwd}",
        f"Workspace-relative location: {relative}",
        "Treat the workspace root as the hard file-operation boundary for this thread.",
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


__all__ = ["render_workspace_context", "workspace_location_path"]
