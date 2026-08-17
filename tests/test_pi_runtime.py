from __future__ import annotations

import hashlib
import io
import json
import platform
import sys
import tarfile
from pathlib import Path

from harness import pi_runtime


def _release_archive(content: bytes) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        member = tarfile.TarInfo("pi/pi")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
        for name in pi_runtime._THEME_MEMBERS:  # noqa: SLF001 - release contract fixture
            theme = b'{}\n'
            member = tarfile.TarInfo(name)
            member.size = len(theme)
            archive.addfile(member, io.BytesIO(theme))
    return stream.getvalue()


def test_materialize_pinned_runtime_at_explicit_init_boundary(tmp_path: Path, monkeypatch) -> None:
    """ADR-013 permits pinned tool materialization only at the explicit init boundary."""

    content = b"standalone-pi"
    archive = _release_archive(content)
    machine = platform.machine().lower()
    machine = "x86_64" if machine in {"amd64", "x64"} else machine
    machine = "arm64" if machine in {"aarch64", "arm64"} else machine
    asset = pi_runtime._ReleaseAsset(  # noqa: SLF001 - exact release seam under test
        "pi-test.tar.gz", hashlib.sha256(archive).hexdigest(), "pi/pi"
    )
    monkeypatch.setattr(pi_runtime, "_source_pi_path", lambda: tmp_path / "missing")
    monkeypatch.setitem(pi_runtime._ASSETS, (sys.platform, machine), asset)
    monkeypatch.setattr(
        pi_runtime.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(archive)
    )

    executable = pi_runtime.ensure_pi_runtime(tmp_path)

    assert executable.read_bytes() == content
    receipt = json.loads(executable.with_suffix(executable.suffix + ".receipt.json").read_text())
    assert receipt["version"] == pi_runtime.PI_VERSION
    assert receipt["archive_sha256"] == asset.sha256
    assert (executable.parent / "theme" / "dark.json").is_file()
    assert pi_runtime.installed_pi_is_ready(tmp_path)

    executable.write_bytes(b"modified")
    assert not pi_runtime.installed_pi_is_ready(tmp_path)

    repaired = pi_runtime.ensure_pi_runtime(tmp_path)
    assert repaired.read_bytes() == content
    assert pi_runtime.installed_pi_is_ready(tmp_path)

    (executable.parent / "theme" / "dark.json").write_text("modified")
    assert not pi_runtime.installed_pi_is_ready(tmp_path)


def test_existing_source_runtime_never_downloads(tmp_path: Path, monkeypatch) -> None:
    """ADR-013 reuses a verified source runtime without hidden network mutation."""

    source = tmp_path / "source-pi"
    source.write_bytes(b"source")
    monkeypatch.setattr(pi_runtime, "_source_pi_path", lambda: source)
    monkeypatch.setattr(
        pi_runtime.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected network")),
    )

    assert pi_runtime.ensure_pi_runtime(tmp_path / "home") == source
