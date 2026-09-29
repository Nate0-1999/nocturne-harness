"""Canonical artificial project paths for M2 project context."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, StrictStr

SEEDED_PROJECT_PATH = "build-test"
PROJECT_PATH_MAX_LENGTH = 4096


def validate_artificial_project_path(value: str) -> str:
    """Return a canonical folder scope key or a tolerated legacy typed project."""

    if not isinstance(value, str):
        raise ValueError("project path must be a string")
    if not value or not value.strip():
        raise ValueError("project path must not be blank")
    if value != value.strip():
        raise ValueError("project path must not have surrounding whitespace")
    if len(value) > PROJECT_PATH_MAX_LENGTH:
        raise ValueError(f"project path must be at most {PROJECT_PATH_MAX_LENGTH} characters")
    if "\\" in value:
        raise ValueError("project path must use POSIX separators")
    segments = value[1:].split("/") if value.startswith("/") else value.split("/")
    if any(segment == "" for segment in segments):
        raise ValueError("project path must not contain empty segments")
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError("project path must not contain dot segments")
    if value.startswith("/") and not value.startswith("//"):
        return value
    if value.startswith("//"):
        raise ValueError("project path must have one absolute root")
    return value


ArtificialProjectPath = Annotated[StrictStr, AfterValidator(validate_artificial_project_path)]


def repository_root(folder: Path) -> Path | None:
    """The git root holding folder (v2.125, F136); None outside a repository."""

    for candidate in (folder, *folder.parents):
        if (candidate / ".git").exists():
            return candidate
    return None
