from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness import browser_runtime


def test_browser_runtime_installs_once_at_explicit_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], Path]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        install_root = Path(environment["PLAYWRIGHT_BROWSERS_PATH"])
        calls.append((command, install_root))
        browser = install_root / "chromium_headless_shell-1234"
        browser.mkdir()
        (browser / "headless_shell").write_bytes(b"browser")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(browser_runtime.subprocess, "run", run)

    installed = browser_runtime.ensure_browser_runtime(tmp_path)

    assert installed == browser_runtime.browser_runtime_path(tmp_path)
    assert browser_runtime.browser_runtime_is_ready(tmp_path)
    assert calls[0][0][-3:] == ["install", "--only-shell", "chromium"]
    assert browser_runtime.ensure_browser_runtime(tmp_path) == installed
    assert len(calls) == 1


def test_browser_runtime_failure_is_plain_and_leaves_no_ready_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        browser_runtime.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "download failed"),
    )

    with pytest.raises(browser_runtime.BrowserRuntimeError, match="nocturne init"):
        browser_runtime.ensure_browser_runtime(tmp_path)

    assert not browser_runtime.browser_runtime_is_ready(tmp_path)
