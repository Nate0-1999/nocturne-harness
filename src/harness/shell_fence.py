"""ADR-015 / F217: Linux mount and namespace walls, shared by the shell and doctor."""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def network_filter(path: Path) -> None:
    """ADR-015: network namespaces alone still expose pathname Unix sockets."""
    library = ctypes.CDLL(ctypes.util.find_library("seccomp") or "libseccomp.so.2")
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    library.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise OSError("Could not initialize the shell network filter")
    try:
        for name in (b"socket", b"socketpair"):
            number = library.seccomp_syscall_resolve_name(name)
            if number < 0 or library.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0):
                raise OSError("Could not build the shell network filter")
        with path.open("wb") as policy:
            if library.seccomp_export_bpf(context, policy.fileno()):
                raise OSError("Could not save the shell network filter")
    finally:
        library.seccomp_release(context)


def linux_fence(*, writable: list[Path], remote: bool) -> list[str]:
    """Start read-only; only explicit locations become writable."""
    arguments = [
        shutil.which("bwrap") or "/usr/bin/bwrap",
        "--unshare-all",
        "--unshare-user",
        "--disable-userns",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
    ]
    if remote:
        arguments.append("--share-net")
    for path in writable:
        path = path.resolve()
        if path.exists():
            arguments.extend(("--bind", str(path), str(path)))
    return arguments


def deny_paths(arguments: list[str], paths: set[Path], *, scratch: Path) -> None:
    """A-084: these masks follow every writable bind, including an owner's grants."""
    empty = scratch / "credential-denied"
    empty.touch(mode=0o000, exist_ok=True)
    denied: list[Path] = []
    for path in sorted({p.resolve() for p in paths}, key=lambda p: len(p.parts)):
        if not path.exists() or any(parent == path or parent in path.parents for parent in denied):
            continue
        if path.is_dir():
            arguments.extend(("--perms", "000", "--tmpfs", str(path), "--remount-ro", str(path)))
        else:
            arguments.extend(("--ro-bind", str(empty), str(path)))
        denied.append(path)


def fence_status() -> tuple[bool, str]:
    """Probe the kernel, not just the presence of an executable; never start an unfenced shell."""
    if sys.platform != "linux":
        ready = Path("/usr/bin/sandbox-exec").is_file()
        return ready, "Seatbelt ready" if ready else "unavailable; use a host with Seatbelt"
    if shutil.which("bwrap") is None:
        return (
            False,
            "unavailable; install bubblewrap (apt install bubblewrap) and enable user namespaces",
        )
    try:
        with tempfile.TemporaryDirectory(prefix="nocturne-fence-probe-") as directory:
            policy = Path(directory) / "network.bpf"
            network_filter(policy)
            with policy.open("rb") as source:
                result = subprocess.run(
                    [
                        *linux_fence(writable=[], remote=False),
                        "--seccomp",
                        str(source.fileno()),
                        "/bin/sh",
                        "-c",
                        "true",
                    ],
                    pass_fds=(source.fileno(),),
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env={"PATH": os.defpath},
                )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is not None and result.returncode == 0:
        return True, "bubblewrap ready (user, mount, PID and network namespaces)"
    return False, (
        "unusable; install libseccomp2, enable user namespaces and permit bubblewrap's "
        "namespace/mount operations "
        "in the host or container policy; then run nocturne doctor again"
    )
