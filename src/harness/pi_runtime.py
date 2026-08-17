"""Explicit, checksummed materialization of the pinned PI standalone runtime."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

PI_VERSION = "0.84.2"
_RELEASE_ROOT = f"https://github.com/earendil-works/pi/releases/download/v{PI_VERSION}"


class PiRuntimeError(RuntimeError):
    """The explicit PI installation boundary could not be completed safely."""


@dataclass(frozen=True, slots=True)
class _ReleaseAsset:
    archive: str
    sha256: str
    member: str


_THEME_MEMBERS = ("pi/theme/dark.json", "pi/theme/light.json", "pi/theme/theme-schema.json")


_ASSETS = {
    ("darwin", "arm64"): _ReleaseAsset(
        "pi-darwin-arm64.tar.gz",
        "c996e888b7f7dce44bcf24f69176ac646c44139d3916bd49a6b28e5a8c5e3a65",
        "pi/pi",
    ),
    ("darwin", "x86_64"): _ReleaseAsset(
        "pi-darwin-x64.tar.gz",
        "808cf02a93cd601d3ea05d47dc15c45074b120ac81decc8644cd3e40a35824e6",
        "pi/pi",
    ),
    ("linux", "arm64"): _ReleaseAsset(
        "pi-linux-arm64.tar.gz",
        "d15372da9e4b4c5fef9fd15bed76d7f5f1720dd39fe7cde0ec62e5b65ad63ef1",
        "pi/pi",
    ),
    ("linux", "x86_64"): _ReleaseAsset(
        "pi-linux-x64.tar.gz",
        "906fbe787fd225c4ac624fe7ebd5b1d55a60e0f5c7ef51795d231564f9ee1c13",
        "pi/pi",
    ),
    ("win32", "arm64"): _ReleaseAsset(
        "pi-windows-arm64.zip",
        "092e2b276e0066efcb3d860465591c2e32ea48ee90395d34ceda0d84d8ff4470",
        "pi/pi.exe",
    ),
    ("win32", "x86_64"): _ReleaseAsset(
        "pi-windows-x64.zip",
        "741fc1ae1afecb573ac2888e011188ff446b3940f4aabe1583f60bf55be8a3d0",
        "pi/pi.exe",
    ),
}


def installed_pi_path(home: Path) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    return home / "tools" / f"pi-{PI_VERSION}" / f"pi{suffix}"


def _source_pi_path() -> Path:
    return (
        Path(__file__).with_name("_pi")
        / "node_modules"
        / ".bin"
        / ("pi.cmd" if os.name == "nt" else "pi")
    )


def pi_runtime_is_ready(home: Path) -> bool:
    return _source_pi_path().is_file() or installed_pi_is_ready(home)


def installed_pi_is_ready(home: Path) -> bool:
    """Verify that the private installed binary still matches its init receipt."""

    target = installed_pi_path(home)
    receipt = target.with_suffix(target.suffix + ".receipt.json")
    if not target.is_file() or not receipt.is_file():
        return False
    try:
        record = json.loads(receipt.read_text(encoding="utf-8"))
        expected = record["binary_sha256"]
        file_hashes = record["file_sha256"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return False
    if not (
        record.get("version") == PI_VERSION
        and isinstance(expected, str)
        and isinstance(file_hashes, dict)
    ):
        return False
    required = (target, *(target.parent / "theme" / Path(member).name for member in _THEME_MEMBERS))
    try:
        return hashlib.sha256(target.read_bytes()).hexdigest() == expected and all(
            isinstance(file_hashes.get(path.relative_to(target.parent).as_posix()), str)
            and hashlib.sha256(path.read_bytes()).hexdigest()
            == file_hashes[path.relative_to(target.parent).as_posix()]
            for path in required
        )
    except OSError:
        return False


def ensure_pi_runtime(home: Path) -> Path:
    """Install PI at the explicit init boundary; never during an owner turn."""

    source_runtime = _source_pi_path()
    if source_runtime.is_file():
        return source_runtime

    target = installed_pi_path(home)
    receipt = target.with_suffix(target.suffix + ".receipt.json")
    if installed_pi_is_ready(home):
        return target

    machine = platform.machine().lower()
    machine = "x86_64" if machine in {"amd64", "x64"} else machine
    machine = "arm64" if machine in {"aarch64", "arm64"} else machine
    try:
        asset = _ASSETS[(sys.platform, machine)]
    except KeyError as exc:
        raise PiRuntimeError(
            f"PI {PI_VERSION} has no supported runtime for {sys.platform}/{machine}."
        ) from exc

    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.parent.chmod(0o700)
    url = f"{_RELEASE_ROOT}/{asset.archive}"
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix="pi-download-", delete=False
        ) as file:
            archive_path = Path(file.name)
            with urllib.request.urlopen(url, timeout=120.0) as response:
                shutil.copyfileobj(response, file)
    except (OSError, urllib.error.URLError) as exc:
        raise PiRuntimeError(
            "PI could not be downloaded during init. Check the connection and run "
            "`nocturne init` again."
        ) from exc

    try:
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if digest != asset.sha256:
            raise PiRuntimeError(
                "PI download failed its pinned SHA-256 check; nothing was installed."
            )
        extracted: dict[str, Path] = {}
        for member_name in (asset.member, *_THEME_MEMBERS):
            relative_name = Path(member_name).relative_to("pi")
            destination = target.parent / relative_name
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=f"{destination.name}-", delete=False
            ) as file:
                temporary_path = Path(file.name)
                extracted[relative_name.as_posix()] = temporary_path
                if asset.archive.endswith(".zip"):
                    with zipfile.ZipFile(archive_path) as archive:
                        with archive.open(member_name) as source:
                            shutil.copyfileobj(source, file)
                else:
                    with tarfile.open(archive_path, mode="r:gz") as archive:
                        member = archive.getmember(member_name)
                        source = archive.extractfile(member)
                        if source is None:
                            raise PiRuntimeError(
                                f"PI release did not contain {relative_name.as_posix()}."
                            )
                        with source:
                            shutil.copyfileobj(source, file)
        binary_path = extracted[Path(asset.member).relative_to("pi").as_posix()]
        binary_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        for relative_name, temporary_path in extracted.items():
            destination = target.parent / relative_name
            os.replace(temporary_path, destination)
            if destination != target:
                destination.chmod(stat.S_IRUSR | stat.S_IWUSR)
        required_paths = (
            target,
            *(target.parent / "theme" / Path(name).name for name in _THEME_MEMBERS),
        )
        file_hashes = {
            path.relative_to(target.parent).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in required_paths
        }
        receipt.write_text(
            json.dumps(
                {
                    "version": PI_VERSION,
                    "source": url,
                    "archive_sha256": digest,
                    "binary_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "file_sha256": file_hashes,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        receipt.chmod(0o600)
        return target
    finally:
        archive_path.unlink(missing_ok=True)
        if "extracted" in locals():
            for temporary_path in extracted.values():
                temporary_path.unlink(missing_ok=True)
