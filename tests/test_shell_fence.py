"""ADR-015 / A-084 / F217: one rule table exercises the real fence on either host."""

import shlex
import socket
import sys
import tempfile
from pathlib import Path

import pytest

from harness.shell_fence import fence_status
from harness.toolset import Crossings, open_standard_toolset


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rule",
    [
        "location",
        "outside",
        "symlink",
        "scratch",
        "network",
        "remote",
        "unix-network",
        "unix-remote",
        "vault",
        "credentials",
    ],
)
async def test_shell_fence_rules(tmp_path: Path, monkeypatch, rule: str):
    """ADR-015, D.2 103, A-084: prevent wrong writes, secret disclosure and network escapes.
    The same table runs on macOS Seatbelt and Linux bubblewrap, without mocked shell results.
    """
    ready, message = fence_status()
    if not ready:
        pytest.skip(message)
    current, outside, home = (tmp_path / name for name in ("current", "outside", "home"))
    for path in (current, outside, home / "vault"):
        path.mkdir(parents=True)
    monkeypatch.setenv("NOCTURNE_HOME", str(home))
    (home / "vault/key.env").write_text("VAULT_MARKER_617")
    (current / ".env").write_text("CREDENTIAL_MARKER_617")
    (current / "link").symlink_to(outside, target_is_directory=True)
    crossings = Crossings(
        thread={"remote", "credentials", f"workspace:{home}"} if rule == "vault" else set()
    )
    if rule in {"remote", "unix-remote"}:
        crossings.thread.add("remote")
    unix = rule.startswith("unix-")
    socket_home = tempfile.TemporaryDirectory(prefix="nocturne-fence-", dir="/tmp")
    socket_path = str(Path(socket_home.name) / "host.sock")
    listener = socket.socket(socket.AF_UNIX if unix else socket.AF_INET)
    listener.bind(socket_path if unix else ("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1] if not unix else None
    network = (
        f"import socket; s=socket.create_connection(('127.0.0.1', {port}), timeout=0.5); "
        "print('NETWORK_REACHED'); s.close()"
    )
    if unix:
        network = (
            f"import socket; s=socket.socket(socket.AF_UNIX); "
            f"s.connect({socket_path!r}); print('NETWORK_REACHED')"
        )

    def python(code):
        return shlex.join([sys.executable, "-c", code])

    commands = {
        "location": "printf allowed > result.txt",
        "outside": f"printf escaped > {shlex.quote(str(outside / 'result.txt'))}",
        "symlink": "printf escaped > link/result.txt",
        "scratch": 'printf scratch > "$TMPDIR/probe"; cat "$TMPDIR/probe"',
        "network": python(network),
        "remote": python(network),
        "unix-network": python(network),
        "unix-remote": python(network),
        "vault": python(
            f"from pathlib import Path; print(Path({str(home / 'vault/key.env')!r}).read_text())"
        ),
        "credentials": "cat .env",
    }
    tools = await open_standard_toolset(cwd=current, workspace_root=current, crossings=crossings)
    try:
        result = await tools.execute("bash", {"command": commands[rule]})
        if rule == "location":
            assert (current / "result.txt").read_text() == "allowed", result.content
        elif rule in {"outside", "symlink"}:
            assert not (outside / "result.txt").exists(), result.content
            assert "exit code" in result.content.lower()
        elif rule == "scratch":
            assert "scratch" in result.content
        elif rule in {"network", "remote", "unix-network", "unix-remote"}:
            assert ("NETWORK_REACHED" in result.content) == rule.endswith("remote"), result.content
        elif rule == "vault":
            assert "VAULT_MARKER_617" not in result.content
            assert "denied" in result.content.lower() or "not permitted" in result.content.lower()
        else:
            assert not result.success and "CREDENTIAL_MARKER_617" not in result.content
    finally:
        listener.close()
        socket_home.cleanup()
        await tools.close()
