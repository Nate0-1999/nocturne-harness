"""The public ``nocturne`` console interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from harness.deploy import DeployError
from harness.lifecycle import LifecycleError
from harness.onboarding import (
    OnboardingError,
    backup_nocturne,
    doctor_nocturne,
    init_nocturne,
    load_config,
    open_nocturne,
    restore_nocturne,
    up_nocturne,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the enacted owner command surface."""

    parser = argparse.ArgumentParser(
        prog="nocturne",
        description="NOCTURNE local harness and Memory Palace",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="initialize a local or remote Palace")
    init.add_argument(
        "--remote",
        metavar="SPINE_URL",
        help="connect this daemon to an existing remote Palace",
    )
    up = commands.add_parser("up", help="start Nocturne for the configured Palace")
    up.add_argument(
        "--no-open",
        action="store_true",
        help="start without opening the browser",
    )
    commands.add_parser("open", help="open the running local Nocturne UI")
    commands.add_parser("backup", help="save a verified local Palace backup")
    restore = commands.add_parser("restore", help="inspect and restore a local Palace backup")
    restore.add_argument("backup_id", help="verified backup generation to restore")
    commands.add_parser("doctor", help="inspect local Palace health and backups")
    deploy = commands.add_parser("deploy", help="reconcile the fixed D1 cloud foundation")
    deploy.add_argument(
        "--dry-run",
        action="store_true",
        help="inspect and print the complete plan without mutation",
    )
    return parser


def _run_cloud_deploy(*, dry_run: bool, openrouter_key: str, home: Path) -> None:
    from harness.deploy import run_cloud_deploy

    run_cloud_deploy(dry_run=dry_run, openrouter_key=openrouter_key, home=home)


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
            init_nocturne(remote=args.remote, stdout=stdout)
        elif args.command == "up":
            up_nocturne(open_browser=not args.no_open, stdout=stdout)
        elif args.command == "open":
            open_nocturne(stdout=stdout)
        elif args.command == "backup":
            backup_nocturne(stdout=stdout)
        elif args.command == "restore":
            return restore_nocturne(args.backup_id, stdout=stdout)
        elif args.command == "doctor":
            return doctor_nocturne(stdout=stdout)
        elif args.command == "deploy":
            config = load_config()
            _run_cloud_deploy(
                dry_run=args.dry_run,
                openrouter_key=config.openrouter_api_key,
                home=config.home,
            )
        else:  # pragma: no cover - argparse owns the closed command set
            raise AssertionError(f"unhandled command: {args.command}")
    except (DeployError, LifecycleError, OnboardingError) as exc:
        print(f"nocturne: {exc}", file=stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
