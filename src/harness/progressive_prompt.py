"""Bounded local directory context for R16 progressive prompting."""

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
_MAX_DIRECTORY_ENTRIES = 80
_MAX_INSTRUCTION_CHARS = 12_000


def workspace_location_path(location: AgentLocation) -> str:
    """Return the one canonical workspace-relative directory for location scoring."""

    root = location.workspace_root.resolve(strict=True)
    cwd = location.cwd.resolve(strict=True)
    if not cwd.is_relative_to(root):  # pragma: no cover - AgentLocation invariant guard
        raise ValueError("agent location escaped its workspace")
    relative = cwd.relative_to(root)
    return "." if not relative.parts else relative.as_posix()


def render_workspace_context(location: AgentLocation) -> str:
    """Render bounded CWD facts and root-to-location agent instructions."""

    root = location.workspace_root.resolve(strict=True)
    cwd = location.cwd.resolve(strict=True)
    relative = workspace_location_path(location)
    entries = _directory_entries(cwd)
    instruction_sections = _instruction_sections(root, cwd)
    lines = [
        "<workspace_context>",
        f"Current location: {relative}",
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
    if len(rendered) > _MAX_DIRECTORY_ENTRIES:
        omitted = len(rendered) - _MAX_DIRECTORY_ENTRIES
        rendered = rendered[:_MAX_DIRECTORY_ENTRIES] + [f"… {omitted} more"]
    return tuple(rendered) if rendered else ("(empty)",)


def _instruction_sections(root: Path, cwd: Path) -> tuple[str, ...]:
    directories = [root]
    if cwd != root:
        current = root
        for segment in cwd.relative_to(root).parts:
            current = current / segment
            directories.append(current)

    remaining = _MAX_INSTRUCTION_CHARS
    sections: list[str] = []
    for directory in directories:
        selected = next(
            (directory / name for name in _INSTRUCTION_NAMES if (directory / name).is_file()), None
        )
        if selected is None:
            continue
        try:
            resolved = selected.resolve(strict=True)
            if not resolved.is_relative_to(root):
                continue
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        label = resolved.relative_to(root).as_posix()
        allowance = max(0, remaining - len(label) - 20)
        if allowance == 0:
            sections.append("[instruction context truncated]")
            break
        clipped = content[:allowance]
        suffix = "\n[truncated]" if len(content) > allowance else ""
        section = f"--- {label} ---\n{clipped}{suffix}"
        sections.append(section)
        remaining -= len(section)
        if remaining <= 0:
            break
    return tuple(sections)


__all__ = ["render_workspace_context", "workspace_location_path"]
