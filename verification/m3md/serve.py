"""M3MD walk: start the packaged app as `nocturne up` does for a remote Palace, on port 8785,
so peers keep 8765 (the only port `up` binds). After M3CL2's serve.py."""

import os
import sys

from harness.onboarding import load_config

config = load_config()
os.execvpe(
    sys.executable,
    [sys.executable, "-m", "uvicorn", "harness.packaged:create_app", "--factory",
     "--host", "127.0.0.1", "--port", "8785"],
    dict(config.process_environment()),
)
