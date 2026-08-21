"""Explicit installation boundary for Playwright's pinned headless Chromium."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

PLAYWRIGHT_VERSION = version("playwright")


class BrowserRuntimeError(RuntimeError):
    """The headless browser runtime could not be prepared during init."""


def browser_runtime_path(home: Path) -> Path:
    return home / "tools" / f"playwright-{PLAYWRIGHT_VERSION}"


def browser_runtime_is_ready(home: Path) -> bool:
    target = browser_runtime_path(home)
    receipt = target / "nocturne-receipt.json"
    try:
        record = json.loads(receipt.read_text(encoding="utf-8"))
        entries = tuple(target.iterdir())
    except (OSError, json.JSONDecodeError):
        return False
    return record == {"playwright_version": PLAYWRIGHT_VERSION} and any(
        entry.is_dir() and entry.name.startswith("chromium_headless_shell-")
        for entry in entries
    )


def ensure_browser_runtime(home: Path) -> Path:
    """Install Chromium at explicit init time, never during an owner turn."""

    target = browser_runtime_path(home)
    if browser_runtime_is_ready(home):
        return target
    tools = target.parent
    tools.mkdir(parents=True, exist_ok=True, mode=0o700)
    tools.chmod(0o700)
    temporary = Path(tempfile.mkdtemp(prefix="playwright-install-", dir=tools))
    environment = dict(os.environ)
    environment["PLAYWRIGHT_BROWSERS_PATH"] = str(temporary)
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=300,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise BrowserRuntimeError(
                "Chromium could not be installed during init. Check the connection and run "
                f"`nocturne init` again. {detail}".strip()
            )
        (temporary / "nocturne-receipt.json").write_text(
            json.dumps({"playwright_version": PLAYWRIGHT_VERSION}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if target.exists():
            shutil.rmtree(target)
        temporary.replace(target)
        return target
    except (OSError, subprocess.SubprocessError) as exc:
        raise BrowserRuntimeError(
            "Chromium could not be installed during init. Check the connection and run "
            "`nocturne init` again."
        ) from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
