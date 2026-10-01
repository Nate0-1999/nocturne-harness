"""M3UI2 walk: start the packaged app exactly as `nocturne up` does for a remote Palace,
on port 8772 so a peer packet can hold 8765."""

import os
import sys

from harness.onboarding import load_config

config = load_config()
os.execvpe(
    sys.executable,
    [
        sys.executable,
        "-m",
        "uvicorn",
        "harness.packaged:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "8772",
    ],
    dict(config.process_environment()),
)
