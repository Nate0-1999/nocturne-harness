"""Reviewed upstream launcher and release archives. Download only on explicit install."""

import base64
import hashlib
import json
import os
import platform
import tarfile
import tempfile
from pathlib import Path

import httpx

VERSION = "0.1.11"
LAUNCHER_INTEGRITY = (
    "sha512-LwGw1MBUrKJfqjTl/75QpAPbD3TBoyyPA8NgNrQh0yb0cQHG"
    "zoOBYuHcZa17rRcbLAULGCf9Bn/9ntEYUmxlLw=="
)
RUNTIME_DIGESTS = {
    "darwin-arm64": "4bc22e16a2e48d868ad8c4b9d6c8e031be1c566ce31c28267955c2986a70e95f",
    "linux-arm64": "7d90a5af032fe0988a616403e0f51a6cb68eff7ed7a84bc40999cc3997dffd71",
    "linux-x64": "2b691c07f5bcb5adea4a863d5324aae7db21bd6d82280cec7787836dcaa013e1",
    "win32-arm64": "777f3c52140a75916fa682b9b3df25be6f9913afb8f12d3e64240661835f7028",
    "win32-x64": "02c92be05c4007339119c39cfc7db06335ee17563dd17c4ada72bcc43cba9d34",
}


class InstallError(RuntimeError):
    pass


def _fetch(url, path, algorithm, expected):
    digest = hashlib.new(algorithm)
    try:
        with httpx.stream(
            "GET", url, follow_redirects=True, timeout=60, trust_env=False
        ) as response:
            response.raise_for_status()
            with path.open("xb") as output:
                for chunk in response.iter_bytes(256 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
    except httpx.HTTPError:
        raise InstallError("Could not download the pinned T3 package.") from None
    if digest.digest() != expected:
        raise InstallError("The downloaded T3 package failed its integrity check.")


def _platform_key() -> str:
    arch = {"aarch64": "arm64", "x86_64": "x64"}.get(platform.machine(), platform.machine())
    return f"{platform.system().lower()}-{arch}"


def _bundle_digest(bundle: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(bundle.rglob("*")):
        if path == bundle / "install-receipt.json":
            continue
        if path.is_symlink():
            content = b"link:" + os.fsencode(os.readlink(path))
        elif path.is_file():
            with path.open("rb") as stream:
                content = hashlib.file_digest(stream, "sha256").digest()
        else:
            continue
        digest.update(os.fsencode(path.relative_to(bundle)) + b"\x00" + content + b"\x00")
    return digest.hexdigest()


def verify_install(bundle: Path) -> None:
    try:
        receipt = json.loads((bundle / "install-receipt.json").read_text())
        valid = (
            receipt["runtime_sha256"] == RUNTIME_DIGESTS[_platform_key()]
            and receipt["launcher_integrity"] == LAUNCHER_INTEGRITY
            and receipt["installed_sha256"] == _bundle_digest(bundle)
        )
    except (KeyError, TypeError, OSError, ValueError):
        valid = False
    if not valid:
        raise InstallError(
            "The local T3 installation failed verification. Move its version folder "
            "aside and run nocturne t3 install."
        )


def install(home: Path) -> Path:
    key = _platform_key()
    if key not in RUNTIME_DIGESTS:
        raise InstallError("There is no supported T3 runtime for this platform.")
    root = home / "t3" / "install"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = root / VERSION
    if destination.exists():
        verify_install(destination)
        return destination
    stem = f"t3-{VERSION}-{key}"
    with tempfile.TemporaryDirectory(dir=root) as staging:
        stage = Path(staging)
        _fetch(
            f"https://registry.npmjs.org/t3/-/t3-{VERSION}.tgz",
            stage / "launcher.tgz",
            "sha512",
            base64.b64decode(LAUNCHER_INTEGRITY.split("-", 1)[1]),
        )
        _fetch(
            f"https://github.com/pingdotgg/t3code/releases/download/v{VERSION}/{stem}.tar.gz",
            stage / "runtime.tgz",
            "sha256",
            bytes.fromhex(RUNTIME_DIGESTS[key]),
        )
        with tarfile.open(stage / "runtime.tgz") as archive:
            archive.extractall(stage, filter="data")
        bundle = stage / stem
        with tarfile.open(stage / "launcher.tgz") as archive:
            archive.extractall(bundle / "launcher", filter="data")
        if (
            not os.access(bundle / "t3", os.X_OK)
            or not (bundle / "launcher/package/bin/t3.mjs").is_file()
        ):
            raise InstallError("The verified archive is missing its runtime or launcher.")
        receipt = {
            "runtime_sha256": RUNTIME_DIGESTS[key],
            "launcher_integrity": LAUNCHER_INTEGRITY,
            "installed_sha256": _bundle_digest(bundle),
        }
        (bundle / "install-receipt.json").write_text(json.dumps(receipt))
        try:
            bundle.rename(destination)
        except OSError:
            if not destination.is_dir():
                raise
            verify_install(destination)
        return destination
