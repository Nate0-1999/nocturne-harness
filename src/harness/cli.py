"""The four-command public ``nocturne`` console interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TextIO

from harness.deploy import DeployError
from harness.onboarding import (
    OnboardingError,
    init_nocturne,
    load_config,
    open_nocturne,
    up_nocturne,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the exact ADR-019 command surface."""

    parser = argparse.ArgumentParser(
        prog="nocturne",
        description="NOCTURNE local harness and Memory Palace",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="initialize with one OpenRouter key")
    up = commands.add_parser("up", help="start local pgvector, Spine, and Nocturne")
    up.add_argument(
        "--no-open",
        action="store_true",
        help="start without opening the browser",
    )
    commands.add_parser("open", help="open the running local Nocturne UI")
    deploy = commands.add_parser("deploy", help="reconcile the fixed D1 cloud foundation")
    deploy.add_argument(
        "--dry-run",
        action="store_true",
        help="inspect and print the complete plan without mutation",
    )
    return parser


def _run_cloud_deploy(*, dry_run: bool, openrouter_key: str) -> None:
    from harness.deploy import run_cloud_deploy

    run_cloud_deploy(dry_run=dry_run, openrouter_key=openrouter_key)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Dispatch one public command and normalize safe operator errors."""

    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            init_nocturne(stdout=stdout)
        elif args.command == "up":
            up_nocturne(open_browser=not args.no_open, stdout=stdout)
        elif args.command == "open":
            open_nocturne(stdout=stdout)
        elif args.command == "deploy":
            config = load_config()
            _run_cloud_deploy(
                dry_run=args.dry_run,
                openrouter_key=config.openrouter_api_key,
            )
        else:  # pragma: no cover - argparse owns the closed command set
            raise AssertionError(f"unhandled command: {args.command}")
    except (DeployError, OnboardingError) as exc:
        print(f"nocturne: {exc}", file=stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
