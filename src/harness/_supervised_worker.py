"""Private launch gate for supervisor-owned worker processes."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Execute a worker only after its durable launch record exists."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) < 2:
        return 125
    try:
        gate_descriptor = int(arguments[0])
    except ValueError:
        return 125
    command = arguments[1:]
    try:
        release = os.read(gate_descriptor, 1)
    finally:
        os.close(gate_descriptor)
    if release != b"1":
        return 125
    os.execvp(command[0], command)
    return 125  # pragma: no cover - exec replaces the process


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
