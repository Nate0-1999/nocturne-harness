"""Read-only discovery of agent instruction files for the seed consent queue."""

import os
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from harness.seed_identity import seed_batch_uid

_AGENT_FILE_NAMES = frozenset({"AGENTS.md", "CLAUDE.md"})
_SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".nocturne",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)
_MAX_AGENT_FILES = 64
_MAX_SEED_BYTES = 24 * 1024


class AgentFileOffer(BaseModel):
    """One local instruction file the owner may explicitly send to seed ingestion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_uid: UUID
    relative_path: str
    source_name: str
    markdown: str
    byte_count: int


class AgentFileOffers(BaseModel):
    """Bounded deterministic discovery result for the Memory Ingest module."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    files: list[AgentFileOffer]
    truncated: bool


def discover_agent_files(root: Path) -> AgentFileOffers:
    """Find eligible AGENTS.md/CLAUDE.md files without following workspace symlinks."""

    scan_root = root.resolve()
    offers: list[AgentFileOffer] = []
    seen_documents: set[tuple[str, str]] = set()
    truncated = False

    if not scan_root.is_dir():
        return AgentFileOffers(files=[], truncated=False)

    for directory, names, filenames in os.walk(scan_root, followlinks=False):
        directory_path = Path(directory)
        names[:] = sorted(
            name
            for name in names
            if name not in _SKIPPED_DIRECTORIES
            and not name.startswith(".")
            and not (directory_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            if filename not in _AGENT_FILE_NAMES:
                continue
            path = directory_path / filename
            if path.is_symlink():
                continue
            try:
                payload = path.read_bytes()
                markdown = payload.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if not markdown.strip() or len(payload) > _MAX_SEED_BYTES:
                continue
            identity = (filename, markdown)
            if identity in seen_documents:
                continue
            seen_documents.add(identity)
            if len(offers) == _MAX_AGENT_FILES:
                truncated = True
                return AgentFileOffers(files=offers, truncated=truncated)
            offers.append(
                AgentFileOffer(
                    batch_uid=seed_batch_uid(filename, markdown),
                    relative_path=path.relative_to(scan_root).as_posix(),
                    source_name=filename,
                    markdown=markdown,
                    byte_count=len(payload),
                )
            )

    return AgentFileOffers(files=offers, truncated=truncated)
