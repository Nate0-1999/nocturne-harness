"""Installed-wheel or editable-checkout factory for the owner app."""

import shutil
from pathlib import Path

from fastapi import FastAPI

from harness.daemon import _build_web, create_dev_app

BUNDLED_WEB_DIST = Path(__file__).with_name("_web")
_CANONICAL_WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
_SOURCE_BUILD_REMEDY = (
    "Nocturne's web app is missing. Install Node.js, then run `npm ci && npm run build` "
    "in the checkout's `web` directory and run `nocturne up` again."
)
_SOURCE_BUILD_FAILED_REMEDY = (
    "Nocturne could not build its web app. Run `npm ci && npm run build` in the checkout's "
    "`web` directory, then run `nocturne up` again."
)
_WHEEL_REINSTALL_REMEDY = (
    "Nocturne's web app files are missing. Reinstall `nocturne-ai`, then run "
    "`nocturne up` again."
)


def _runtime_web_assets() -> tuple[Path, str | None]:
    """Resolve the same web build from a wheel or the canonical editable checkout."""

    if (BUNDLED_WEB_DIST / "index.html").is_file():
        return BUNDLED_WEB_DIST, None

    checkout_dist = _CANONICAL_WEB_ROOT / "dist"
    if (_CANONICAL_WEB_ROOT / "package.json").is_file():
        if (checkout_dist / "index.html").is_file():
            return checkout_dist, None
        if shutil.which("npm") is not None:
            try:
                _build_web(_CANONICAL_WEB_ROOT)
            except SystemExit:
                return checkout_dist, _SOURCE_BUILD_FAILED_REMEDY
            if (checkout_dist / "index.html").is_file():
                return checkout_dist, None
            return checkout_dist, _SOURCE_BUILD_FAILED_REMEDY
        return checkout_dist, _SOURCE_BUILD_REMEDY

    return BUNDLED_WEB_DIST, _WHEEL_REINSTALL_REMEDY


def create_app() -> FastAPI:
    """Compose the owner app from installed or canonical source assets."""

    web_dist, missing_web_message = _runtime_web_assets()
    return create_dev_app(
        web_dist,
        missing_web_message=missing_web_message or _SOURCE_BUILD_REMEDY,
    )
