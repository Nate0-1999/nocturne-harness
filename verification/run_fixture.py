"""Foreground-only fixture launcher with product-port refusal. [A-038]"""

from __future__ import annotations

import argparse

import uvicorn

from verification.fixture_isolation import PRODUCT_PORT


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m verification.run_fixture")
    parser.add_argument(
        "app",
        help=(
            "ASGI factory import, for example "
            "verification.m2g.scenario_app:create_scenario_app"
        ),
    )
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if args.port == PRODUCT_PORT:
        parser.error("port 8765 belongs to the owner app; fixtures must use a distinct port")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    uvicorn.run(args.app, factory=True, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
