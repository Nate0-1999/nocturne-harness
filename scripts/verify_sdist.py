"""Verify that the public nocturne-ai source archive contains product source only."""

from __future__ import annotations

import sys
import tarfile
from pathlib import Path


def main() -> None:
    """Reject relay, verification, test, secret, and build-only material."""

    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_sdist.py DIST.tar.gz")
    archive = Path(sys.argv[1])
    with tarfile.open(archive, "r:gz") as source:
        names = tuple(member.name for member in source.getmembers())

    roots = {name.split("/", 1)[0] for name in names}
    assert len(roots) == 1
    root = roots.pop()
    required = {
        f"{root}/PKG-INFO",
        f"{root}/README.md",
        f"{root}/pyproject.toml",
        f"{root}/src/harness/cli.py",
        f"{root}/src/harness/deploy.py",
        f"{root}/src/harness/resources/docker-compose.yml",
        f"{root}/web/dist/index.html",
    }
    assert required <= set(names)

    forbidden_components = {
        ".env",
        ".git",
        ".github",
        "AGENTS.md",
        "CLAUDE.md",
        "DECISIONS.md",
        "docs",
        "garden",
        "node_modules",
        "tests",
        "uv.lock",
        "verification",
    }
    for name in names:
        relative = Path(name).parts[1:]
        assert not forbidden_components.intersection(relative), name

    print(f"nocturne-ai sdist scope passed ({len(names)} entries)")


if __name__ == "__main__":
    main()
