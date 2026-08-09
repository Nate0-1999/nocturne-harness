"""Canonical artificial project paths for M2 project context."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StrictStr

SEEDED_PROJECT_PATH = "build-test"
PROJECT_PATH_MAX_LENGTH = 256


def validate_artificial_project_path(value: str) -> str:
    """Return one canonical relative POSIX project path or raise ``ValueError``."""

    if not isinstance(value, str):
        raise ValueError("project path must be a string")
    if not value or not value.strip():
        raise ValueError("project path must not be blank")
    if value != value.strip():
        raise ValueError("project path must not have surrounding whitespace")
    if len(value) > PROJECT_PATH_MAX_LENGTH:
        raise ValueError(f"project path must be at most {PROJECT_PATH_MAX_LENGTH} characters")
    if value.startswith("/"):
        raise ValueError("project path must be relative")
    if "\\" in value:
        raise ValueError("project path must use POSIX separators")
    segments = value.split("/")
    if any(segment == "" for segment in segments):
        raise ValueError("project path must not contain empty segments")
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError("project path must not contain dot segments")
    return value


ArtificialProjectPath = Annotated[StrictStr, AfterValidator(validate_artificial_project_path)]
