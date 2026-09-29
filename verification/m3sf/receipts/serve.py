"""M3SF walk: start the packaged app exactly as `nocturne up` does for a remote Palace,
on port 8766 because a peer packet's app already holds 8765."""

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
        "8766",
    ],
    dict(config.process_environment()),
)
