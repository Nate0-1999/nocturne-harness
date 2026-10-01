"""M3CL2 walk: start the packaged app as `nocturne up` does for a remote Palace, on port 8767,
because a peer packet's walk needs 8765 (the only port `up` binds). After M3SF's serve.py."""

import os
import sys

from harness.onboarding import load_config

config = load_config()
os.execvpe(
    sys.executable,
    [sys.executable, "-m", "uvicorn", "harness.packaged:create_app", "--factory",
     "--host", "127.0.0.1", "--port", "8767"],
    dict(config.process_environment()),
)
