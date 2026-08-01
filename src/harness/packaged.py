"""Installed-wheel application factory using bundled, prebuilt web assets."""

from pathlib import Path

from fastapi import FastAPI

from harness.daemon import create_dev_app

BUNDLED_WEB_DIST = Path(__file__).with_name("_web")


def create_app() -> FastAPI:
    """Compose the production local app without invoking Node or repository paths."""

    return create_dev_app(BUNDLED_WEB_DIST)
